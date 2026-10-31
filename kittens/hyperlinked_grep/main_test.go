// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package hyperlinked_grep

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

var _ = fmt.Print

func TestRgArgParsing(t *testing.T) {
	if RgExe() == "rg" {
		t.Skip("Skipping as rg not found in PATH")
	}

	check_failure := func(args ...string) {
		_, _, _, err := parse_args(args...)
		if err == nil {
			t.Fatalf("No error when parsing: %#v", args)
		}
	}
	check_failure("--kitten", "xyz")
	check_failure("--kitten", "xyz=1")

	check_kitten_opts := func(matching, context, headers bool, args ...string) {
		_, _, kitten_opts, err := parse_args(args...)
		if err != nil {
			t.Fatalf("error when parsing: %#v: %s", args, err)
		}
		if matching != kitten_opts.matching_lines {
			t.Fatalf("Matching lines not correct for: %#v", args)
		}
		if context != kitten_opts.context_lines {
			t.Fatalf("Context lines not correct for: %#v", args)
		}
		if headers != kitten_opts.file_headers {
			t.Fatalf("File headers not correct for: %#v", args)
		}
	}
	check_kitten_opts(true, true, true)
	check_kitten_opts(false, false, false, "--kitten", "hyperlink=none")
	check_kitten_opts(false, false, true, "--kitten", "hyperlink=none", "--count", "--kitten=hyperlink=file_headers")
	check_kitten_opts(false, false, true, "--kitten", "hyperlink=none,file_headers")

	check_kitten_opts = func(with_filename, heading, line_number bool, args ...string) {
		_, _, kitten_opts, err := parse_args(args...)
		if err != nil {
			t.Fatalf("error when parsing: %#v: %s", args, err)
		}
		if with_filename != kitten_opts.with_filename {
			t.Fatalf("with_filename not correct for: %#v", args)
		}
		if heading != kitten_opts.heading {
			t.Fatalf("heading not correct for: %#v", args)
		}
		if line_number != kitten_opts.line_number {
			t.Fatalf("line_number not correct for: %#v", args)
		}
	}

	check_kitten_opts(true, true, true)
	check_kitten_opts(true, false, true, "--no-heading")
	check_kitten_opts(true, true, true, "--no-heading", "--pretty")
	check_kitten_opts(true, true, true, "--no-heading", "--heading")

	check_args := func(args, expected string) {
		a, err := shlex.Split(args)
		if err != nil {
			t.Fatal(err)
		}
		_, actual, _, err := parse_args(a...)
		if err != nil {
			t.Fatalf("error when parsing: %#v: %s", args, err)
		}
		ex, err := shlex.Split(expected)
		if err != nil {
			t.Fatal(err)
		}
		if diff := cmp.Diff(ex, actual); diff != "" {
			t.Fatalf("args not correct for %s\n%s", args, diff)
		}
	}
	check_args("--count --max-depth 10 --XxX yyy abcd", "--count --max-depth 10 --XxX yyy abcd")
	check_args("--max-depth=10 --kitten hyperlink=none abcd", "--max-depth=10 abcd")
	check_args("-m 10 abcd", "--max-count 10 abcd")
	check_args("-nm 10 abcd", "-n --max-count 10 abcd")
	check_args("-mn 10 abcd", "--max-count n 10 abcd")

}

func TestRgArgumentSemantics(t *testing.T) {
	if RgExe() == "rg" {
		t.Skip("Skipping as rg not found in PATH")
	}
	dir := t.TempDir()
	for name, data := range map[string]string{"first.txt": "foo\nfoo.bar\n-f\n--help\nπ\n", "second.txt": "bar\n"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	run := func(t *testing.T, args []string, input string) (int, string) {
		t.Helper()
		common := []string{"--no-config", "--no-heading", "--no-line-number", "--color=never", "--with-filename", "--sort=path"}
		cmd := exec.Command(RgExe(), append(common, args...)...)
		cmd.Dir = dir
		cmd.Stdin = strings.NewReader(input)
		output, err := cmd.Output()
		if err != nil {
			var exit_err *exec.ExitError
			if !errors.As(err, &exit_err) {
				t.Fatal(err)
			}
			return exit_err.ExitCode(), string(output)
		}
		return 0, string(output)
	}
	for _, tc := range []struct {
		name, input string
		args        []string
		exit_code   int
	}{
		{name: "separate_value", args: []string{"-e", "foo", "first.txt", "second.txt"}},
		{name: "attached_value", args: []string{"-efoo", "first.txt", "second.txt"}},
		{name: "grouped_attached_value", args: []string{"-nefoo", "first.txt", "second.txt"}},
		{name: "punctuation_in_value", args: []string{"-efoo.bar", "first.txt", "second.txt"}},
		{name: "hyphen_in_value", args: []string{"-e-f", "first.txt", "second.txt"}},
		{name: "option_like_value", args: []string{"-e--help", "first.txt", "second.txt"}},
		{name: "flag_letters_in_value", args: []string{"-ehelp", "first.txt", "second.txt"}},
		{name: "unicode_value", args: []string{"-eπ", "first.txt", "second.txt"}},
		{name: "attached_glob", args: []string{"-g*.txt", "foo", "."}},
		{name: "attached_literal_glob", args: []string{"-gfirst.txt", "foo", "."}},
		{name: "multiple_patterns", args: []string{"-efoo", "-ebar", "first.txt", "second.txt"}},
		{name: "boolean_group", args: []string{"-nH", "foo", "first.txt", "second.txt"}},
		{name: "stdin_with_file", args: []string{"foo", "-", "second.txt"}, input: "foo from stdin\n"},
		{name: "stdin_only", args: []string{"foo", "-"}, input: "foo from stdin\n"},
		{name: "stdin_after_terminator", args: []string{"foo", "--", "-", "second.txt"}, input: "foo from stdin\n"},
		{name: "pattern_after_terminator", args: []string{"--", "-f", "first.txt", "second.txt"}},
		{name: "invalid_attached_count", args: []string{"-mn", "10", "first.txt", "second.txt"}, exit_code: 2},
		{name: "unknown_option", args: []string{"-n?", "foo", "first.txt", "second.txt"}, exit_code: 2},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, args, _, err := parse_args(tc.args...)
			if err != nil {
				t.Fatal(err)
			}
			want_code, want_output := run(t, tc.args, tc.input)
			if want_code != tc.exit_code {
				t.Fatalf("Unexpected rg exit code for %q: %d != %d", tc.args, want_code, tc.exit_code)
			}
			code, output := run(t, args, tc.input)
			if code != want_code || output != want_output {
				t.Fatalf("Changed rg results for %q (parsed as %q): exit code %d != %d, output %q != %q", tc.args, args, code, want_code, output, want_output)
			}
		})
	}
}
