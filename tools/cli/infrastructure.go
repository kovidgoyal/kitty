// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"

	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
	"golang.org/x/sys/unix"

	"kitty"
	"kitty/tools/cli/markup"
	"kitty/tools/tty"
	"kitty/tools/utils/style"
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

var formatter *markup.Context

func format_with_indent(output io.Writer, text string, indent string, screen_width int) {
	text = formatter.Prettify(text)
	indented := style.WrapText(text, indent, screen_width, "#placeholder_for_formatting#")
	io.WriteString(output, indented)
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
	if formatter.EscapeCodesAllowed() {
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
	fmt.Fprintln(&output, formatter.Title("Usage")+":", formatter.Exe(full_command_name(cmd)), use)
	fmt.Fprintln(&output)
	if len(cmd.Long) > 0 {
		format_with_indent(&output, cmd.Long, "", screen_width)
	} else if len(cmd.Short) > 0 {
		format_with_indent(&output, cmd.Short, "", screen_width)
	}
	if cmd.HasAvailableSubCommands() {
		fmt.Fprintln(&output)
		fmt.Fprintln(&output, formatter.Title("Commands")+":")
		for _, child := range cmd.Commands() {
			if child.Hidden {
				continue
			}
			fmt.Fprintln(&output, " ", formatter.Opt(child.Name()))
			format_with_indent(&output, child.Short, "    ", screen_width)
		}
		fmt.Fprintln(&output)
		format_with_indent(&output, "Get help for an individual command by running:", "", screen_width)
		fmt.Fprintln(&output, "   ", full_command_name(cmd), formatter.Italic("command"), "-h")
	}
	if cmd.HasAvailableFlags() {
		options_title := cmd.Annotations["options_title"]
		if len(options_title) == 0 {
			options_title = "Options"
		}
		fmt.Fprintln(&output)
		fmt.Fprintln(&output, formatter.Title(options_title)+":")
		flag_set := cmd.LocalFlags()
		flag_set.VisitAll(func(flag *pflag.Flag) {
			fmt.Fprint(&output, formatter.Opt("  --"+flag.Name))
			if flag.Shorthand != "" {
				fmt.Fprint(&output, ", ", formatter.Opt("-"+flag.Shorthand))
			}
			defval := ""
			switch flag.Value.Type() {
			default:
				if flag.DefValue != "" {
					defval = fmt.Sprintf("[=%s]", formatter.Italic(flag.DefValue))
				}
			case "stringArray":
				if flag.DefValue != "[]" {
					defval = fmt.Sprintf("[=%s]", formatter.Italic(flag.DefValue))
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
				msg = "Print the version of " + RootCmd.Name() + ": " + formatter.Italic(RootCmd.Version)
			}
			format_with_indent(&output, msg, "    ", screen_width)
			fmt.Fprintln(&output)
		})
	}
	if cmd.Annotations["usage-suffix"] != "" {
		fmt.Fprintln(&output, cmd.Annotations["usage-suffix"])
	} else {
		fmt.Fprintln(&output, formatter.Italic(RootCmd.Name()), formatter.Opt(kitty.VersionString), "created by", formatter.Title("Kovid Goyal"))
	}
	output_text := output.String()
	// fmt.Printf("%#v\n", output_text)
	if use_pager && formatter.EscapeCodesAllowed() && cmd.Annotations["allow-pager"] != "no" {
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
		trailer := fmt.Sprintf("Use %s to get a list of available sub-commands", formatter.Bold(full_command_name(cmd)+" -h"))
		if len(suggestions) > 0 {
			es += "\nDid you mean?\n"
			for _, s := range suggestions {
				es += fmt.Sprintf("\t%s\n", formatter.Italic(s))
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
	fmt.Println(formatter.Err("Error")+":", err)
}

func Init(root *cobra.Command) {
	vs := kitty.VersionString
	if kitty.VCSRevision != "" {
		vs = vs + " (" + kitty.VCSRevision + ")"
	}
	formatter = markup.New(tty.IsTerminal(os.Stdout.Fd()))
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
