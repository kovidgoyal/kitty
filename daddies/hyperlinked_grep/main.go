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

	"github.com/kovidgoyal/datty/tools/cli"
	"github.com/kovidgoyal/datty/tools/utils"

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
				for x := range strings.SplitSeq(s, ",") {
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

type daddy_options struct {
	matching_lines, context_lines, file_headers    bool
	with_filename, heading, line_number            bool
	stats, count, count_matches                    bool
	files, files_with_matches, files_without_match bool
	vimgrep                                        bool
}

func default_daddy_opts() *daddy_options {
	return &daddy_options{
		matching_lines: true, context_lines: true, file_headers: true,
		with_filename: true, heading: true, line_number: true,
	}

}

func parse_args(args ...string) (delegate_to_rg bool, sanitized_args []string, daddy_opts *daddy_options, err error) {
	options_that_expect_args, alias_map, err := get_options_for_rg()
	if err != nil {
		return
	}
	options_that_expect_args["daddy"] = true
	daddy_opts = default_daddy_opts()
	sanitized_args = make([]string, 0, len(args))
	expecting_option_arg := ""

	context_separator := "--"
	field_context_separator := "-"
	field_match_separator := "-"

	handle_option_arg := func(key, val string, with_equals bool) error {
		if key != "daddy" {
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
		case "daddy":
			k, v, found := strings.Cut(val, "=")
			if !found || k != "hyperlink" {
				return fmt.Errorf("Unknown --daddy option: %s", val)
			}
			for x := range strings.SplitSeq(v, ",") {
				switch x {
				case "none":
					daddy_opts.context_lines = false
					daddy_opts.file_headers = false
					daddy_opts.matching_lines = false
				case "all":
					daddy_opts.context_lines = true
					daddy_opts.file_headers = true
					daddy_opts.matching_lines = true
				case "matching_lines":
					daddy_opts.matching_lines = true
				case "file_headers":
					daddy_opts.file_headers = true
				case "context_lines":
					daddy_opts.context_lines = true
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
			daddy_opts.with_filename = false
		case "with-filename":
			daddy_opts.with_filename = true
		case "heading":
			daddy_opts.heading = true
		case "no-heading":
			daddy_opts.heading = false
		case "line-number":
			daddy_opts.line_number = true
		case "no-line-number":
			daddy_opts.line_number = false
		case "pretty":
			daddy_opts.line_number = true
			daddy_opts.heading = true
		case "stats":
			daddy_opts.stats = true
		case "count":
			daddy_opts.count = true
		case "count-matches":
			daddy_opts.count_matches = true
		case "files":
			daddy_opts.files = true
		case "files-with-matches":
			daddy_opts.files_with_matches = true
		case "files-without-match":
			daddy_opts.files_without_match = true
		case "vimgrep":
			daddy_opts.vimgrep = true
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
			} else if x != "-" && strings.HasPrefix(x, "-") {
				// rg semantics: everything after the first short option that
				// takes a value is that value, with an optional leading = stripped
				ok := true
				chars := make([]string, 0, len(x)-1)
				option_arg, has_option_arg := "", false
				for j, ch := range x[1:] {
					chars = append(chars, string(ch))
					var target string
					if target, ok = alias_map[string(ch)]; !ok {
						sanitized_args = append(sanitized_args, x)
						break
					}
					if options_that_expect_args[target] {
						if rest := x[j+2:]; rest != "" {
							option_arg, has_option_arg = strings.TrimPrefix(rest, "="), true
						}
						break
					}
				}
				if ok {
					for _, ch := range chars {
						target := alias_map[ch]
						if options_that_expect_args[target] {
							if !has_option_arg {
								expecting_option_arg = target
							} else if err = handle_option_arg(target, option_arg, false); err != nil {
								return
							}
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
	if !daddy_opts.with_filename || context_separator != "--" || field_context_separator != "-" || field_match_separator != "-" {
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
	delegate_to_rg, sanitized_args, daddy_opts, err := parse_args(args...)
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
			if daddy_opts.line_number {
				m := num_pat.FindStringSubmatch(clean_line)
				if len(m) > 0 {
					is_match_line := len(m) > 1 && m[2] == ":"
					if (is_match_line && daddy_opts.matching_lines) || (!is_match_line && daddy_opts.context_lines) {
						write_hyperlink(in_result, line, m[1])
						return
					}
				}
			}
			write(line, "\n")
		} else {
			if strings.TrimSpace(line) != "" {
				// The option priority should be consistent with ripgrep here.
				if daddy_opts.stats && !in_stats && stats_pat.MatchString(clean_line) {
					in_stats = true
				} else if daddy_opts.count || daddy_opts.count_matches {
					if m := path_with_count_pat.FindStringSubmatch(clean_line); len(m) > 0 && daddy_opts.file_headers {
						write_hyperlink(get_quoted_url(m[1]), line, "")
						return
					}
				} else if daddy_opts.files || daddy_opts.files_with_matches || daddy_opts.files_without_match {
					if daddy_opts.file_headers {
						write_hyperlink(get_quoted_url(clean_line), line, "")
						return
					}
				} else if daddy_opts.vimgrep || !daddy_opts.heading {
					var m []string
					// When the vimgrep option is present, it will take precedence.
					if daddy_opts.vimgrep {
						m = vimgrep_pat.FindStringSubmatch(clean_line)
					} else {
						m = path_with_linenum_pat.FindStringSubmatch(clean_line)
					}
					if len(m) > 0 && (daddy_opts.file_headers || daddy_opts.matching_lines) {
						write_hyperlink(get_quoted_url(m[1]), line, m[2])
						return
					}
				} else {
					in_result = get_quoted_url(clean_line)
					if daddy_opts.file_headers {
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
	hg.HelpText = "The hyperlinked_grep daddy is a thin wrapper around the rg command. It automatically adds hyperlinks to the output of rg allowing the user to click on search results to have them open directly in their editor. For details on its usage, see :doc:`/daddies/hyperlinked_grep`."
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
