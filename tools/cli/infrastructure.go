package cli

import (
	"fmt"
	"os"
	"regexp"
	"strings"
	"syscall"
	"unicode"
	"unsafe"

	"github.com/fatih/color"
	runewidth "github.com/mattn/go-runewidth"
	"github.com/spf13/cobra"
	"github.com/spf13/pflag"

	"kitty"
)

var RootCmd *cobra.Command

type Winsize struct {
	Rows    uint16
	Cols    uint16
	Xpixels uint16
	Ypixels uint16
}

func GetTTYSize() (Winsize, error) {
	var ws Winsize
	f, err := os.OpenFile("/dev/tty", os.O_RDONLY, 0755)
	if err != nil {
		return ws, err
	}
	fd := f.Fd()
	retCode, _, errno := syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), uintptr(syscall.TIOCGWINSZ), uintptr(unsafe.Pointer(&ws)))
	f.Close()

	if int(retCode) == -1 {
		return ws, errno
	}
	return ws, nil
}

func add_choices(cmd *cobra.Command, flags *pflag.FlagSet, choices []string, name string, usage string) {
	flags.String(name, choices[0], usage)
	cmd.Annotations["choices-"+name] = strings.Join(choices, "\000")
}

func Choices(cmd *cobra.Command, name string, usage string, choices ...string) {
	add_choices(cmd, cmd.Flags(), choices, name, usage)
}

func PersistentChoices(cmd *cobra.Command, name string, usage string, choices ...string) {
	add_choices(cmd, cmd.PersistentFlags(), choices, name, usage)
}

func key_in_slice(vals []string, key string) bool {
	for _, q := range vals {
		if q == key {
			return true
		}
	}
	return false
}

func ValidateChoices(cmd *cobra.Command, args []string) error {
	for key, val := range cmd.Annotations {
		if strings.HasPrefix(key, "choices-") {
			allowed := strings.Split(val, "\000")
			name := key[len("choices-"):]
			if cval, err := cmd.Flags().GetString(name); err == nil && !key_in_slice(allowed, cval) {
				return fmt.Errorf("%s: Invalid value: %s. Allowed values are: %s", color.YellowString("--"+name), color.RedString(cval), strings.Join(allowed, ", "))
			}
		}
	}
	return nil
}

var title_fmt = color.New(color.FgBlue, color.Bold).SprintFunc()
var exe_fmt = color.New(color.FgYellow, color.Bold).SprintFunc()
var opt_fmt = color.New(color.FgGreen).SprintFunc()
var italic_fmt = color.New(color.Italic).SprintFunc()
var bold_fmt = color.New(color.Bold).SprintFunc()
var code_fmt = color.New(color.FgCyan).SprintFunc()
var cyan_fmt = color.New(color.FgCyan).SprintFunc()
var yellow_fmt = color.New(color.FgYellow).SprintFunc()
var blue_fmt = color.New(color.FgBlue).SprintFunc()
var green_fmt = color.New(color.FgGreen).SprintFunc()

func cmd_name(cmd *cobra.Command) string {
	if cmd.Annotations != nil {
		parts := strings.Split(cmd.Annotations["exe"], " ")
		return parts[len(parts)-1]
	}
	return cmd.Name()
}

func print_created_by(root *cobra.Command) {
	fmt.Println(italic_fmt(root.Annotations["exe"]), opt_fmt(root.Version), "created by", title_fmt("Kovid Goyal"))
}

func print_line_with_indent(text string, indent string, screen_width int) {
	x := len(indent)
	fmt.Print(indent)
	in_sgr := false
	var current_word strings.Builder

	print_word := func(r rune) {
		w := runewidth.StringWidth(current_word.String())
		if x+w > screen_width {
			fmt.Println()
			fmt.Print(indent)
			x = len(indent)
			s := strings.TrimSpace(current_word.String())
			current_word.Reset()
			current_word.WriteString(s)
		}
		fmt.Print(current_word.String())
		current_word.Reset()
		if r > 0 {
			current_word.WriteRune(r)
		}
		x += w
	}

	for _, r := range text {
		if in_sgr {
			if r == 'm' {
				in_sgr = false
			}
			fmt.Print(string(r))
			continue
		}
		if r == 0x1b {
			in_sgr = true
			if current_word.Len() != 0 {
				print_word(0)
			}
			fmt.Print(string(r))
			continue
		}
		if current_word.Len() != 0 && r != 0xa0 && unicode.IsSpace(r) {
			print_word(r)
		} else {
			current_word.WriteRune(r)
		}
	}
	if current_word.Len() != 0 {
		print_word(0)
	}
	if len(text) > 0 {
		fmt.Println()
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
	return kitty.WebsiteBaseUrl + doc
}

var prettify_pat = regexp.MustCompile(":([a-z]+):`([^`]+)`")
var ref_pat = regexp.MustCompile(`\s*<\S+?>`)

func prettify(text string) string {
	return ReplaceAllStringSubmatchFunc(prettify_pat, text, func(groups []string) string {
		val := groups[2]
		switch groups[1] {
		case "file", "env", "envvar":
			return italic_fmt(val)
		case "doc":
			return website_url(val)
		case "ref":
			return ref_pat.ReplaceAllString(val, ``)
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

func print_with_indent(text string, indent string, screen_width int) {
	for _, line := range strings.Split(prettify(text), "\n") {
		print_line_with_indent(line, indent, screen_width)
	}
}

func show_usage(cmd *cobra.Command) error {
	ws, tty_size_err := GetTTYSize()
	screen_width := 80
	if tty_size_err == nil && ws.Cols < 80 {
		screen_width = int(ws.Cols)
	}
	fmt.Println(title_fmt("Usage")+":", exe_fmt(cmd.Annotations["exe"]), cmd.Use)
	fmt.Println()
	if len(cmd.Long) > 0 {
		print_with_indent(cmd.Long, "", screen_width)
	} else if len(cmd.Short) > 0 {
		print_with_indent(cmd.Short, "", screen_width)
	}
	if cmd.HasAvailableSubCommands() {
		fmt.Println()
		fmt.Println(title_fmt("Commands") + ":")
		for _, child := range cmd.Commands() {
			fmt.Println(" ", opt_fmt(cmd_name(child)))
			print_with_indent(child.Short, "    ", screen_width)
		}
		fmt.Println()
		print_with_indent("Get help for an individual command by running:", "", screen_width)
		fmt.Println("   ", cmd.Annotations["exe"], italic_fmt("command"), "-h")
	}
	if cmd.HasAvailableFlags() {
		options_title := cmd.Annotations["options_title"]
		if len(options_title) == 0 {
			options_title = "Options"
		}
		fmt.Println()
		fmt.Println(title_fmt(options_title) + ":")
		flag_set := cmd.LocalFlags()
		flag_set.VisitAll(func(flag *pflag.Flag) {
			fmt.Print(opt_fmt("  --" + flag.Name))
			if flag.Shorthand != "" {
				fmt.Print(", ", opt_fmt("-"+flag.Shorthand))
			}
			defval := ""
			switch flag.Value.Type() {
			default:
				defval = fmt.Sprintf("[=%s]", italic_fmt(flag.DefValue))
			case "bool":
			case "count":
			}
			if defval != "" {
				fmt.Print(" ", defval)
			}
			fmt.Println()
			msg := flag.Usage
			switch flag.Name {
			case "help":
				msg = "Print this help message"
			case "version":
				msg = "Print the version of " + RootCmd.Annotations["exe"] + ": " + italic_fmt(RootCmd.Version)
			}
			print_with_indent(msg, "    ", screen_width)
			if cmd.Annotations["choices-"+flag.Name] != "" {
				fmt.Println("    Choices:", strings.Join(strings.Split(cmd.Annotations["choices-"+flag.Name], "\000"), ", "))
			}
			fmt.Println()
		})
	}
	if cmd.HasParent() {
		cmd.VisitParents(func(cmd *cobra.Command) {
			if !cmd.HasParent() {
				print_created_by(cmd)
			}
		})
	} else {
		print_created_by(cmd)
	}

	return nil
}

func CreateCommand(cmd *cobra.Command, exe string) *cobra.Command {
	cmd.Annotations = make(map[string]string)
	cmd.Annotations["exe"] = exe
	return cmd
}

func Init(root *cobra.Command) {
	RootCmd = root
	root.Version = kitty.VersionString
	root.PersistentPreRunE = ValidateChoices
	root.SetUsageFunc(show_usage)
	root.SetHelpTemplate("{{.UsageString}}")
}
