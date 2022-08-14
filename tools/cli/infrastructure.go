package cli

import (
	"fmt"
	"os"
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

func print_with_indent(text string, indent string, screen_width int) {
	x := len(indent)
	fmt.Print(indent)
	in_sgr := false
	current_word := ""

	print_word := func(r rune) {
		w := runewidth.StringWidth(current_word)
		if x+w > screen_width {
			fmt.Println()
			fmt.Print(indent)
			x = len(indent)
			current_word = strings.TrimSpace(current_word)
		}
		fmt.Print(current_word)
		current_word = string(r)
		x += w
	}

	for _, r := range text {
		if in_sgr {
			if r == 'm' {
				in_sgr = false
			}
			continue
		}
		if r == 0x1b {
			in_sgr = true
			continue
		}
		if current_word != "" && unicode.IsSpace(r) && r != 0xa0 {
			print_word(r)
		} else {
			current_word += string(r)
		}
	}
	if current_word != "" {
		print_word(' ')
		fmt.Print(current_word)
	}
	if len(text) > 0 {
		fmt.Println()
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
			if flag.Name == "help" {
				fmt.Println("   ", "Print this help message")
				fmt.Println()
				return
			}
			for _, line := range strings.Split(flag.Usage, "\n") {
				print_with_indent(line, "    ", screen_width)
			}
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
	root.Version = kitty.VersionString
	root.PersistentPreRunE = ValidateChoices
	root.SetUsageFunc(show_usage)
	root.SetHelpTemplate("{{.UsageString}}")
}
