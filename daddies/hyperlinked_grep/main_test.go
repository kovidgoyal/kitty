// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package hyperlinked_grep

import (
	"fmt"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/datty/tools/utils/shlex"
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
	check_failure("--daddy", "xyz")
	check_failure("--daddy", "xyz=1")

	check_daddy_opts := func(matching, context, headers bool, args ...string) {
		_, _, daddy_opts, err := parse_args(args...)
		if err != nil {
			t.Fatalf("error when parsing: %#v: %s", args, err)
		}
		if matching != daddy_opts.matching_lines {
			t.Fatalf("Matching lines not correct for: %#v", args)
		}
		if context != daddy_opts.context_lines {
			t.Fatalf("Context lines not correct for: %#v", args)
		}
		if headers != daddy_opts.file_headers {
			t.Fatalf("File headers not correct for: %#v", args)
		}
	}
	check_daddy_opts(true, true, true)
	check_daddy_opts(false, false, false, "--daddy", "hyperlink=none")
	check_daddy_opts(false, false, true, "--daddy", "hyperlink=none", "--count", "--daddy=hyperlink=file_headers")
	check_daddy_opts(false, false, true, "--daddy", "hyperlink=none,file_headers")

	check_daddy_opts = func(with_filename, heading, line_number bool, args ...string) {
		_, _, daddy_opts, err := parse_args(args...)
		if err != nil {
			t.Fatalf("error when parsing: %#v: %s", args, err)
		}
		if with_filename != daddy_opts.with_filename {
			t.Fatalf("with_filename not correct for: %#v", args)
		}
		if heading != daddy_opts.heading {
			t.Fatalf("heading not correct for: %#v", args)
		}
		if line_number != daddy_opts.line_number {
			t.Fatalf("line_number not correct for: %#v", args)
		}
	}

	check_daddy_opts(true, true, true)
	check_daddy_opts(true, false, true, "--no-heading")
	check_daddy_opts(true, true, true, "--no-heading", "--pretty")
	check_daddy_opts(true, true, true, "--no-heading", "--heading")

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
	check_args("--max-depth=10 --daddy hyperlink=none abcd", "--max-depth=10 abcd")
	check_args("-m 10 abcd", "--max-count 10 abcd")
	check_args("-nm 10 abcd", "-n --max-count 10 abcd")
	check_args("-mn 10 abcd", "--max-count n 10 abcd")
	check_args("-efoo a", "--regexp foo a")
	check_args("-nefoo a", "-n --regexp foo a")
	check_args("-e-f a", "--regexp -f a")
	check_args("-eπ a", "--regexp π a")
	check_args("-e=foo a", "--regexp foo a")
	check_args("-e==foo a", "--regexp =foo a")
	check_args("-e= a", "--regexp '' a")
	check_args("'-g*.txt' foo .", "--glob '*.txt' foo .")
	check_args("foo - a", "foo - a")
	check_args("-e - a", "--regexp - a")
	check_args("'-n?' foo", "'-n?' foo")
	check_args("foo -- -n -", "foo -- -n -")
}
