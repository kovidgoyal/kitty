// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package hyperlinked_grep

import (
	"bytes"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"unicode"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/utils"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

var RgExe = sync.OnceValue(func() string {
	return utils.FindExe("rg")
})

func get_options_for_rg() (expecting_args map[string]bool, alias_map map[string]string, err error) {
	var raw []byte
	raw, err = exec.Command(RgExe(), "--help").Output()
	if err != nil {
		err = fmt.Errorf("Failed to execute rg: %w", err)
		return
	}
	scanner := utils.NewLineScanner(utils.UnsafeBytesToString(raw))
	options_started := false
	expecting_args = make(map[string]bool, 64)
	alias_map = make(map[string]string, 52)
	for scanner.Scan() {
		line := scanner.Text()
		if options_started {
			s := strings.TrimLeft(line, " ")
			indent := len(line) - len(s)
			if indent < 8 && indent > 0 {
				expecting_arg := strings.Contains(s, "=")
				single_letter_aliases := make([]string, 0, 1)
				long_option_names := make([]string, 0, 1)
				for _, x := range strings.Split(s, ",") {
					x = strings.TrimSpace(x)
					if strings.HasPrefix(x, "--") {
						lon, _, _ := strings.Cut(x[2:], "=")
						long_option_names = append(long_option_names, lon)
					} else if strings.HasPrefix(x, "-") {
						son, _, _ := strings.Cut(x[1:], " ")
						single_letter_aliases = append(single_letter_aliases, son)
					}
				}
				if len(long_option_names) == 0 {
					err = fmt.Errorf("Failed to parse rg help output line: %s", line)
					return
				}
				for _, x := range single_letter_aliases {
					alias_map[x] = long_option_names[0]
				}
				for _, x := range long_option_names[1:] {
					alias_map[x] = long_option_names[0]
				}
				expecting_args[long_option_names[0]] = expecting_arg
			}
		} else {
			if strings.HasSuffix(line, "OPTIONS:") {
				options_started = true
			}
		}
	}
	if len(expecting_args) == 0 || len(alias_map) == 0 {
		err = fmt.Errorf("Failed to parse rg help output, could not find any options")
		return
	}
	return
}

type kitten_options struct {
	matching_lines, context_lines, file_headers    bool
	with_filename, heading, line_number            bool
	stats, count, count_matches                    bool
	files, files_with_matches, files_without_match bool
	vimgrep                                        bool
}

func default_kitten_opts() *kitten_options {
	return &kitten_options{
		matching_lines: true, context_lines: true, file_headers: true,
		with_filename: true, heading: true, line_number: true,
	}

}

func parse_args(args ...string) (delegate_to_rg bool, sanitized_args []string, kitten_opts *kitten_options, err error) {
	options_that_expect_args, alias_map, err := get_options_for_rg()
	if err != nil {
		return
	}
	options_that_expect_args["kitten"] = true
	kitten_opts = default_kitten_opts()
	sanitized_args = make([]string, 0, len(args))
	expecting_option_arg := ""

	context_separator := "--"
	field_context_separator := "-"
	field_match_separator := "-"

	handle_option_arg := func(key, val string, with_equals bool) error {
		if key != "kitten" {
			if with_equals {
				sanitized_args = append(sanitized_args, "--"+key+"="+val)
			} else {
				sanitized_args = append(sanitized_args, "--"+key, val)
			}
		}
		switch key {
		case "path-separator":
			if val != string(os.PathSeparator) {
				delegate_to_rg = true
			}
		case "context-separator":
			context_separator = val
		case "field-context-separator":
			field_context_separator = val
		case "field-match-separator":
			field_match_separator = val
		case "kitten":
			k, v, found := strings.Cut(val, "=")
			if !found || k != "hyperlink" {
				return fmt.Errorf("Unknown --kitten option: %s", val)
			}
			for _, x := range strings.Split(v, ",") {
				switch x {
				case "none":
					kitten_opts.context_lines = false
					kitten_opts.file_headers = false
					kitten_opts.matching_lines = false
				case "all":
					kitten_opts.context_lines = true
					kitten_opts.file_headers = true
					kitten_opts.matching_lines = true
				case "matching_lines":
					kitten_opts.matching_lines = true
				case "file_headers":
					kitten_opts.file_headers = true
				case "context_lines":
					kitten_opts.context_lines = true
				default:
					return fmt.Errorf("hyperlink option invalid: %s", x)
				}
			}
		}
		return nil
	}

	handle_bool_option := func(key string) {
		switch key {
		case "no-context-separator":
			context_separator = ""
		case "no-filename":
			kitten_opts.with_filename = false
		case "with-filename":
			kitten_opts.with_filename = true
		case "heading":
			kitten_opts.heading = true
		case "no-heading":
			kitten_opts.heading = false
		case "line-number":
			kitten_opts.line_number = true
		case "no-line-number":
			kitten_opts.line_number = false
		case "pretty":
			kitten_opts.line_number = true
			kitten_opts.heading = true
		case "stats":
			kitten_opts.stats = true
		case "count":
			kitten_opts.count = true
		case "count-matches":
			kitten_opts.count_matches = true
		case "files":
			kitten_opts.files = true
		case "files-with-matches":
			kitten_opts.files_with_matches = true
		case "files-without-match":
			kitten_opts.files_without_match = true
		case "vimgrep":
			kitten_opts.vimgrep = true
		case "null", "null-data", "type-list", "version", "help":
			delegate_to_rg = true
		}
	}

	for i, x := range args {
		if expecting_option_arg != "" {
			if err = handle_option_arg(expecting_option_arg, x, false); err != nil {
				return
			}
			expecting_option_arg = ""
		} else {
			if x == "--" {
				sanitized_args = append(sanitized_args, args[i:]...)
				break
			}
			if strings.HasPrefix(x, "--") {
				a, b, found := strings.Cut(x, "=")
				a = a[2:]
				q := alias_map[a]
				if q != "" {
					a = q
				}
				if found {
					if _, is_known_option := options_that_expect_args[a]; is_known_option {
						if err = handle_option_arg(a, b, true); err != nil {
							return
						}
					} else {
						sanitized_args = append(sanitized_args, x)
					}
				} else {
					if options_that_expect_args[a] {
						expecting_option_arg = a
					} else {
						handle_bool_option(a)
						sanitized_args = append(sanitized_args, x)
					}
				}
			} else if strings.HasPrefix(x, "-") {
				ok := true
				chars := make([]string, len(x)-1)
				for i, ch := range x[1:] {
					chars[i] = string(ch)
					_, ok = alias_map[string(ch)]
					if !ok {
						sanitized_args = append(sanitized_args, x)
						break
					}
				}
				if ok {
					for _, ch := range chars {
						target := alias_map[ch]
						if options_that_expect_args[target] {
							expecting_option_arg = target
						} else {
							handle_bool_option(target)
							sanitized_args = append(sanitized_args, "-"+ch)
						}
					}
				}
			} else {
				sanitized_args = append(sanitized_args, x)
			}
		}
	}
	if !kitten_opts.with_filename || context_separator != "--" || field_context_separator != "-" || field_match_separator != "-" {
		delegate_to_rg = true
	}
	return
}

type stdout_filter struct {
	prefix       []byte
	process_line func(string)
}

func (self *stdout_filter) Write(p []byte) (n int, err error) {
	n = len(p)
	for len(p) > 0 {
		idx := bytes.IndexByte(p, '\n')
		if idx < 0 {
			self.prefix = append(self.prefix, p...)
			break
		}
		line := p[:idx]
		if len(self.prefix) > 0 {
			self.prefix = append(self.prefix, line...)
			line = self.prefix
		}
		p = p[idx+1:]
		self.process_line(utils.UnsafeBytesToString(line))
		self.prefix = self.prefix[:0]
	}
	return
}

func main(_ *cli.Command, _ *Options, args []string) (rc int, err error) {
	delegate_to_rg, sanitized_args, kitten_opts, err := parse_args(args...)
	if err != nil {
		return 1, err
	}
	if delegate_to_rg {
		sanitized_args = append([]string{"rg"}, sanitized_args...)
		err = unix.Exec(RgExe(), sanitized_args, os.Environ())
		if err != nil {
			err = fmt.Errorf("Failed to execute rg: %w", err)
			rc = 1
		}
		return
	}
	cmdline := append([]string{"--pretty", "--with-filename"}, sanitized_args...)
	cmd := exec.Command(RgExe(), cmdline...)
	cmd.Stdin = os.Stdin
	cmd.Stderr = os.Stderr
	buf := stdout_filter{prefix: make([]byte, 0, 8*1024)}
	cmd.Stdout = &buf
	sgr_pat := regexp.MustCompile("\x1b\\[.*?m")
	osc_pat := regexp.MustCompile("\x1b\\].*?\x1b\\\\")
	num_pat := regexp.MustCompile(`^(\d+)([:-])`)
	path_with_count_pat := regexp.MustCompile(`^(.*?)(:\d+)`)
	path_with_linenum_pat := regexp.MustCompile(`^(.*?):(\d+):`)
	stats_pat := regexp.MustCompile(`^\d+ matches$`)
	vimgrep_pat := regexp.MustCompile(`^(.*?):(\d+):(\d+):`)

	in_stats := false
	in_result := ""
	hostname := utils.Hostname()

	get_quoted_url := func(file_path string) string {
		q, err := filepath.Abs(file_path)
		if err == nil {
			file_path = q
		}
		file_path = filepath.ToSlash(file_path)
		file_path = strings.Join(utils.Map(url.PathEscape, strings.Split(file_path, "/")), "/")
		return "file://" + hostname + file_path
	}

	write := func(items ...string) {
		for _, x := range items {
			os.Stdout.WriteString(x)
		}
	}

	write_hyperlink := func(url, line, frag string) {
		write("\033]8;;", url)
		if frag != "" {
			write("#", frag)
		}
		write("\033\\", line, "\n\033]8;;\033\\")
	}

	buf.process_line = func(line string) {
		line = osc_pat.ReplaceAllLiteralString(line, "") // remove existing hyperlinks
		clean_line := strings.TrimRightFunc(line, unicode.IsSpace)
		clean_line = sgr_pat.ReplaceAllLiteralString(clean_line, "") // remove SGR formatting
		if clean_line == "" {
			in_result = ""
			write("\n")
		} else if in_stats {
			write(line, "\n")
		} else if in_result != "" {
			if kitten_opts.line_number {
				m := num_pat.FindStringSubmatch(clean_line)
				if len(m) > 0 {
					is_match_line := len(m) > 1 && m[2] == ":"
					if (is_match_line && kitten_opts.matching_lines) || (!is_match_line && kitten_opts.context_lines) {
						write_hyperlink(in_result, line, m[1])
						return
					}
				}
			}
			write(line, "\n")
		} else {
			if strings.TrimSpace(line) != "" {
				// The option priority should be consistent with ripgrep here.
				if kitten_opts.stats && !in_stats && stats_pat.MatchString(clean_line) {
					in_stats = true
				} else if kitten_opts.count || kitten_opts.count_matches {
					if m := path_with_count_pat.FindStringSubmatch(clean_line); len(m) > 0 && kitten_opts.file_headers {
						write_hyperlink(get_quoted_url(m[1]), line, "")
						return
					}
				} else if kitten_opts.files || kitten_opts.files_with_matches || kitten_opts.files_without_match {
					if kitten_opts.file_headers {
						write_hyperlink(get_quoted_url(clean_line), line, "")
						return
					}
				} else if kitten_opts.vimgrep || !kitten_opts.heading {
					var m []string
					// When the vimgrep option is present, it will take precedence.
					if kitten_opts.vimgrep {
						m = vimgrep_pat.FindStringSubmatch(clean_line)
					} else {
						m = path_with_linenum_pat.FindStringSubmatch(clean_line)
					}
					if len(m) > 0 && (kitten_opts.file_headers || kitten_opts.matching_lines) {
						write_hyperlink(get_quoted_url(m[1]), line, m[2])
						return
					}
				} else {
					in_result = get_quoted_url(clean_line)
					if kitten_opts.file_headers {
						write_hyperlink(in_result, line, "")
						return
					}
				}
			}
			write(line, "\n")
		}
	}

	err = cmd.Run()
	var ee *exec.ExitError
	if err != nil {
		if errors.As(err, &ee) {
			return ee.ExitCode(), nil
		}
		return 1, fmt.Errorf("Failed to execute rg: %w", err)
	}

	return
}

func specialize_command(hg *cli.Command) {
	hg.Usage = "arguments for the rg command"
	hg.ShortDescription = "Add hyperlinks to the output of ripgrep"
	hg.HelpText = "The hyperlinked_grep kitten is a thin wrapper around the rg command. It automatically adds hyperlinks to the output of rg allowing the user to click on search results to have them open directly in their editor. For details on its usage, see :doc:`/kittens/hyperlinked_grep`."
	hg.IgnoreAllArgs = true
	hg.OnlyArgsAllowed = true
	hg.ArgCompleter = cli.CompletionForWrapper("rg")
}

type Options struct {
}

func create_cmd(root *cli.Command, run_func func(*cli.Command, *Options, []string) (int, error)) {
	ans := root.AddSubCommand(&cli.Command{
		Name: "hyperlinked_grep",
		Run: func(cmd *cli.Command, args []string) (int, error) {
			opts := Options{}
			err := cmd.GetOptionValues(&opts)
			if err != nil {
				return 1, err
			}
			return run_func(cmd, &opts, args)
		},
		Hidden: true,
	})
	specialize_command(ans)
	clone := root.AddClone(ans.Group, ans)
	clone.Hidden = false
	clone.Name = "hyperlinked-grep"
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
