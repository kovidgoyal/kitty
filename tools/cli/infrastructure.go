// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"unicode"

	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
	"golang.org/x/sys/unix"

	"kitty"
	"kitty/tools/tty"
	"kitty/tools/utils"
	"kitty/tools/utils/style"
	"kitty/tools/wcswidth"
)

var RootCmd *cobra.Command

func key_in_slice(vals []string, key string) bool {
	for _, q := range vals {
		if q == key {
			return true
		}
	}
	return false
}

type ChoicesVal struct {
	name, Choice string
	allowed      []string
}
type choicesVal ChoicesVal

func (i *choicesVal) String() string { return ChoicesVal(*i).Choice }
func (i *choicesVal) Type() string   { return "string" }
func (i *choicesVal) Set(s string) error {
	(*i).Choice = s
	return nil
}
func newChoicesVal(val ChoicesVal, p *ChoicesVal) *choicesVal {
	*p = val
	return (*choicesVal)(p)
}

func add_choices(flags *pflag.FlagSet, p *ChoicesVal, choices []string, name string, short string, usage string) {
	usage = strings.TrimSpace(usage) + "\n" + "Choices: " + strings.Join(choices, ", ")
	value := ChoicesVal{Choice: choices[0], allowed: choices}
	flags.VarP(newChoicesVal(value, p), name, short, usage)
}

func Choices(flags *pflag.FlagSet, name string, usage string, choices ...string) *ChoicesVal {
	p := new(ChoicesVal)
	add_choices(flags, p, choices, name, "", usage)
	return p
}

func ChoicesP(flags *pflag.FlagSet, name string, short string, usage string, choices ...string) *ChoicesVal {
	p := new(ChoicesVal)
	add_choices(flags, p, choices, name, short, usage)
	return p
}

var stdout_is_terminal = false

var (
	fmt_ctx        = style.Context{}
	cyan_fmt       = fmt_ctx.SprintFunc("fg=bright-cyan")
	green_fmt      = fmt_ctx.SprintFunc("fg=green")
	blue_fmt       = fmt_ctx.SprintFunc("fg=blue")
	bright_red_fmt = fmt_ctx.SprintFunc("fg=bright-red")
	yellow_fmt     = fmt_ctx.SprintFunc("fg=bright-yellow")
	italic_fmt     = fmt_ctx.SprintFunc("italic")
	bold_fmt       = fmt_ctx.SprintFunc("bold")
	title_fmt      = fmt_ctx.SprintFunc("bold fg=blue")
	exe_fmt        = fmt_ctx.SprintFunc("bold fg=bright-yellow")
	opt_fmt        = green_fmt
	emph_fmt       = bright_red_fmt
	err_fmt        = fmt_ctx.SprintFunc("bold fg=bright-red")
	code_fmt       = cyan_fmt
	url_fmt        = fmt_ctx.UrlFunc("u=curly uc=cyan")
)

func format_line_with_indent(output io.Writer, text string, indent string, screen_width int) {
	trimmed := strings.TrimSpace(text)
	if trimmed == "" {
		fmt.Fprintln(output, indent)
		return
	}
	if trimmed == "#placeholder_for_formatting#" {
		return
	}
	x := len(indent)
	fmt.Fprint(output, indent)
	in_escape := 0
	var current_word strings.Builder
	var escapes strings.Builder

	print_word := func(r rune) {
		w := wcswidth.Stringwidth(current_word.String())
		if x+w > screen_width {
			fmt.Fprintln(output)
			fmt.Fprint(output, indent)
			x = len(indent)
			s := strings.TrimSpace(current_word.String())
			current_word.Reset()
			current_word.WriteString(s)
		}
		if escapes.Len() > 0 {
			output.Write([]byte(escapes.String()))
			escapes.Reset()
		}
		if current_word.Len() > 0 {
			output.Write([]byte(current_word.String()))
			current_word.Reset()
		}
		if r > 0 {
			current_word.WriteRune(r)
		}
		x += w
	}

	for i, r := range text {
		if in_escape > 0 {
			if in_escape == 1 && (r == ']' || r == '[') {
				in_escape = 2
				if r == ']' {
					in_escape = 3
				}
			}
			if (in_escape == 2 && r == 'm') || (in_escape == 3 && r == '\\' && text[i-1] == 0x1b) {
				in_escape = 0
			}
			escapes.WriteRune(r)
			continue
		}
		if r == 0x1b {
			in_escape = 1
			if current_word.Len() != 0 {
				print_word(0)
			}
			escapes.WriteRune(r)
			continue
		}
		if current_word.Len() != 0 && r != 0xa0 && unicode.IsSpace(r) {
			print_word(r)
		} else {
			current_word.WriteRune(r)
		}
	}
	if current_word.Len() != 0 || escapes.Len() != 0 {
		print_word(0)
	}
	if len(text) > 0 {
		fmt.Fprintln(output)
	}
}

func ReplaceAllStringSubmatchFunc(re *regexp.Regexp, str string, repl func([]string) string) string {
	result := ""
	lastIndex := 0

	for _, v := range re.FindAllSubmatchIndex([]byte(str), -1) {
		groups := []string{}
		for i := 0; i < len(v); i += 2 {
			if v[i] == -1 || v[i+1] == -1 {
				groups = append(groups, "")
			} else {
				groups = append(groups, str[v[i]:v[i+1]])
			}
		}

		result += str[lastIndex:v[0]] + repl(groups)
		lastIndex = v[1]
	}

	return result + str[lastIndex:]
}

func website_url(doc string) string {
	if doc != "" {
		doc = strings.TrimSuffix(doc, "/")
		if doc != "" {
			doc += "/"
		}
	}
	return kitty.WebsiteBaseURL + doc
}

var prettify_pat = regexp.MustCompile(":([a-z]+):`([^`]+)`")

func hyperlink_for_url(url string, text string) string {
	return url_fmt(url, text)
}

var hostname string = "*"

func CachedHostname() string {
	if hostname == "*" {
		h, err := os.Hostname()
		if err != nil {
			hostname = h
		} else {
			hostname = ""
		}
	}
	return hostname
}

func hyperlink_for_path(path string, text string) string {
	if !fmt_ctx.AllowEscapeCodes {
		return text
	}
	path = strings.ReplaceAll(utils.Abspath(path), string(os.PathSeparator), "/")
	fi, err := os.Stat(path)
	if err == nil && fi.IsDir() {
		path = strings.TrimSuffix(path, "/") + "/"
	}
	host := CachedHostname()
	url := "file://" + host + path
	return hyperlink_for_url(url, text)
}

func text_and_target(x string) (text string, target string) {
	parts := strings.SplitN(x, "<", 2)
	text = strings.TrimSpace(parts[0])
	target = strings.TrimRight(parts[len(parts)-1], ">")
	return
}

func ref_hyperlink(x string, prefix string) string {
	text, target := text_and_target(x)
	url := "kitty+doc://" + CachedHostname() + "/#ref=" + prefix + target
	return hyperlink_for_url(url, text)
}

func prettify(text string) string {
	return ReplaceAllStringSubmatchFunc(prettify_pat, text, func(groups []string) string {
		val := groups[2]
		switch groups[1] {
		case "file":
			if val == "kitty.conf" && stdout_is_terminal {
				path := filepath.Join(utils.ConfigDir(), val)
				val = hyperlink_for_path(path, val)
			}
			return italic_fmt(val)
		case "env", "envvar":
			return ref_hyperlink(val, "envvar-")
		case "doc":
			text, target := text_and_target(val)
			if text == target {
				target = strings.Trim(target, "/")
				if title, ok := kitty.DocTitleMap[target]; ok {
					val = title + " <" + target + ">"
				}
			}
			return ref_hyperlink(val, "doc-")
		case "iss":
			return ref_hyperlink(val, "issues-")
		case "pull":
			return ref_hyperlink(val, "pull-")
		case "disc":
			return ref_hyperlink(val, "discussions-")
		case "ref":
			return ref_hyperlink(val, "")
		case "ac":
			return ref_hyperlink(val, "action-")
		case "term":
			return ref_hyperlink(val, "term-")
		case "code":
			return code_fmt(val)
		case "option":
			idx := strings.LastIndex(val, "--")
			if idx < 0 {
				idx = strings.Index(val, "-")
			}
			if idx > -1 {
				val = val[idx:]
			}
			return bold_fmt(val)
		case "opt":
			return bold_fmt(val)
		case "yellow":
			return yellow_fmt(val)
		case "blue":
			return blue_fmt(val)
		case "green":
			return green_fmt(val)
		case "cyan":
			return cyan_fmt(val)
		case "emph":
			return italic_fmt(val)
		default:
			return val
		}

	})
}

func format_with_indent(output io.Writer, text string, indent string, screen_width int) {
	for _, line := range strings.Split(prettify(text), "\n") {
		format_line_with_indent(output, line, indent, screen_width)
	}
}

func full_command_name(cmd *cobra.Command) string {
	var parent_names []string
	cmd.VisitParents(func(p *cobra.Command) {
		parent_names = append([]string{p.Name()}, parent_names...)
	})
	parent_names = append(parent_names, cmd.Name())
	return strings.Join(parent_names, " ")
}

func show_usage(cmd *cobra.Command, use_pager bool) error {
	screen_width := 80
	if stdout_is_terminal {
		var sz *unix.Winsize
		var tty_size_err error
		for {
			sz, tty_size_err = unix.IoctlGetWinsize(int(os.Stdout.Fd()), unix.TIOCGWINSZ)
			if tty_size_err != unix.EINTR {
				break
			}
		}
		if tty_size_err == nil && sz.Col < 80 {
			screen_width = int(sz.Col)
		}
	}
	var output strings.Builder
	use := cmd.Use
	idx := strings.Index(use, " ")
	if idx > -1 {
		use = use[idx+1:]
	} else {
		use = ""
	}
	fmt.Fprintln(&output, title_fmt("Usage")+":", exe_fmt(full_command_name(cmd)), use)
	fmt.Fprintln(&output)
	if len(cmd.Long) > 0 {
		format_with_indent(&output, cmd.Long, "", screen_width)
	} else if len(cmd.Short) > 0 {
		format_with_indent(&output, cmd.Short, "", screen_width)
	}
	if cmd.HasAvailableSubCommands() {
		fmt.Fprintln(&output)
		fmt.Fprintln(&output, title_fmt("Commands")+":")
		for _, child := range cmd.Commands() {
			if child.Hidden {
				continue
			}
			fmt.Fprintln(&output, " ", opt_fmt(child.Name()))
			format_with_indent(&output, child.Short, "    ", screen_width)
		}
		fmt.Fprintln(&output)
		format_with_indent(&output, "Get help for an individual command by running:", "", screen_width)
		fmt.Fprintln(&output, "   ", full_command_name(cmd), italic_fmt("command"), "-h")
	}
	if cmd.HasAvailableFlags() {
		options_title := cmd.Annotations["options_title"]
		if len(options_title) == 0 {
			options_title = "Options"
		}
		fmt.Fprintln(&output)
		fmt.Fprintln(&output, title_fmt(options_title)+":")
		flag_set := cmd.LocalFlags()
		flag_set.VisitAll(func(flag *pflag.Flag) {
			fmt.Fprint(&output, opt_fmt("  --"+flag.Name))
			if flag.Shorthand != "" {
				fmt.Fprint(&output, ", ", opt_fmt("-"+flag.Shorthand))
			}
			defval := ""
			switch flag.Value.Type() {
			default:
				if flag.DefValue != "" {
					defval = fmt.Sprintf("[=%s]", italic_fmt(flag.DefValue))
				}
			case "stringArray":
				if flag.DefValue != "[]" {
					defval = fmt.Sprintf("[=%s]", italic_fmt(flag.DefValue))
				}
			case "bool":
			case "count":
			}
			if defval != "" {
				fmt.Fprint(&output, " ", defval)
			}
			fmt.Fprintln(&output)
			msg := flag.Usage
			switch flag.Name {
			case "help":
				msg = "Print this help message"
			case "version":
				msg = "Print the version of " + RootCmd.Name() + ": " + italic_fmt(RootCmd.Version)
			}
			format_with_indent(&output, msg, "    ", screen_width)
			fmt.Fprintln(&output)
		})
	}
	if cmd.Annotations["usage-suffix"] != "" {
		fmt.Fprintln(&output, cmd.Annotations["usage-suffix"])
	} else {
		fmt.Fprintln(&output, italic_fmt(RootCmd.Name()), opt_fmt(kitty.VersionString), "created by", title_fmt("Kovid Goyal"))
	}
	output_text := output.String()
	// fmt.Printf("%#v\n", output_text)
	if use_pager && stdout_is_terminal && cmd.Annotations["allow-pager"] != "no" {
		pager := exec.Command(kitty.DefaultPager[0], kitty.DefaultPager[1:]...)
		pager.Stdin = strings.NewReader(output_text)
		pager.Stdout = os.Stdout
		pager.Stderr = os.Stderr
		pager.Run()
	} else {
		cmd.OutOrStdout().Write([]byte(output_text))
	}
	return nil
}

func FlagNormalizer(name string) string {
	return strings.ReplaceAll(name, "_", "-")
}

func DisallowArgs(cmd *cobra.Command, args []string) error {
	if cmd.HasSubCommands() {
		if len(args) == 0 {
			return fmt.Errorf("No sub-command specified. Use %s -h to get a list of available sub-commands", full_command_name(cmd))
		}
		cmd.SuggestionsMinimumDistance = 2
		suggestions := cmd.SuggestionsFor(args[0])
		es := "Not a valid subcommand: " + args[0]
		trailer := fmt.Sprintf("Use %s to get a list of available sub-commands", bold_fmt(full_command_name(cmd)+" -h"))
		if len(suggestions) > 0 {
			es += "\nDid you mean?\n"
			for _, s := range suggestions {
				es += fmt.Sprintf("\t%s\n", italic_fmt(s))
			}
			es += trailer
		} else {
			es += ". " + trailer
		}
		return fmt.Errorf("%s", es)
	}
	return nil
}

func CreateCommand(cmd *cobra.Command) *cobra.Command {
	cmd.Annotations = make(map[string]string)
	cmd.SilenceErrors = true
	cmd.SilenceUsage = true
	cmd.PersistentFlags().SortFlags = false
	cmd.Flags().SortFlags = false
	cmd.Flags().SetNormalizeFunc(func(fs *pflag.FlagSet, name string) pflag.NormalizedName {
		return pflag.NormalizedName(FlagNormalizer(name))
	})
	cmd.PersistentFlags().SetNormalizeFunc(cmd.Flags().GetNormalizeFunc())
	if !cmd.Runnable() {
		cmd.Args = DisallowArgs
		cmd.RunE = func(cmd *cobra.Command, args []string) error {
			return nil
		}
	}
	return cmd
}

func show_help(cmd *cobra.Command, args []string) {
	show_usage(cmd, true)
}

func PrintError(err error) {
	fmt.Println(err_fmt("Error")+":", err)
}

func Init(root *cobra.Command) {
	vs := kitty.VersionString
	if kitty.VCSRevision != "" {
		vs = vs + " (" + kitty.VCSRevision + ")"
	}
	stdout_is_terminal = tty.IsTerminal(os.Stdout.Fd())
	fmt_ctx.AllowEscapeCodes = stdout_is_terminal
	RootCmd = root
	root.Version = vs
	root.SetUsageFunc(func(cmd *cobra.Command) error { return show_usage(cmd, false) })
	root.SetHelpFunc(show_help)
	root.SetHelpCommand(&cobra.Command{Hidden: true})
	root.CompletionOptions.DisableDefaultCmd = true
}

func Execute(root *cobra.Command) error {
	return root.Execute()
}

type FlagValGetter struct {
	Flags *pflag.FlagSet
	Err   error
}

func (self *FlagValGetter) String(name string) string {
	if self.Err != nil {
		return ""
	}
	ans, err := self.Flags.GetString(name)
	self.Err = err
	return ans
}
