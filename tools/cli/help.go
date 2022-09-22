// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"

	"golang.org/x/sys/unix"

	"kitty"
	"kitty/tools/cli/markup"
	"kitty/tools/tty"
	"kitty/tools/utils/style"
)

var _ = fmt.Print

func ShowError(err error) {
	formatter := markup.New(tty.IsTerminal(os.Stderr.Fd()))
	msg := formatter.Prettify(err.Error())
	fmt.Fprintln(os.Stderr, formatter.Err("Error")+":", msg)
}

func (self *Command) ShowVersion() {
	formatter := markup.New(tty.IsTerminal(os.Stdout.Fd()))
	fmt.Fprintln(os.Stdout, formatter.Italic(self.CommandStringForUsage()), formatter.Opt(kitty.VersionString), "created by", formatter.Title("Kovid Goyal"))
}

func format_with_indent(output io.Writer, text string, indent string, screen_width int) {
	text = formatter.Prettify(text)
	indented := style.WrapText(text, indent, screen_width, "#placeholder_for_formatting#")
	io.WriteString(output, indented)
}

func (self *Command) FormatSubCommands(output io.Writer, formatter *markup.Context, screen_width int) {
	for _, g := range self.SubCommandGroups {
		if !g.HasVisibleSubCommands() {
			continue
		}
		fmt.Fprintln(output)
		if g.Title != "" {
			fmt.Fprintln(output, formatter.Title(g.Title))
		}
		for _, c := range g.SubCommands {
			if c.Hidden {
				continue
			}
			fmt.Fprintln(output, "  ", formatter.Opt(c.Name))
			format_with_indent(output, formatter.Prettify(c.ShortDescription), "    ", screen_width)
		}
	}

}

func (self *Option) FormatOption(output io.Writer, formatter *markup.Context, screen_width int) {
	for i, a := range self.Aliases {
		fmt.Fprint(output, formatter.Opt(a.String()))
		if i != len(self.Aliases)-1 {
			fmt.Fprint(output, ", ")
		}
	}
	defval := ""
	switch self.OptionType {
	case BoolOption:
	default:
		defval = self.Default
		fallthrough
	case StringOption:
		if self.IsList {
			defval = ""
		}
	}
	if defval != "" {
		fmt.Fprintf(output, " [=%s]", formatter.Italic(defval))
	}
	fmt.Fprintln(output)
	format_with_indent(output, formatter.Prettify(prepare_help_text_for_display(self.Help)), "    ", screen_width)
}

func (self *Command) ShowHelp() {
	formatter := markup.New(tty.IsTerminal(os.Stdout.Fd()))
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

	fmt.Fprintln(&output, formatter.Title("Usage")+":", formatter.Exe(strings.TrimSpace(self.CommandStringForUsage())),
		strings.TrimSpace(formatter.Prettify(self.Usage)))
	fmt.Fprintln(&output)
	format_with_indent(&output, formatter.Prettify(prepare_help_text_for_display(self.HelpText)), "", screen_width)

	if self.HasVisibleSubCommands() {
		fmt.Fprintln(&output)
		fmt.Fprintln(&output, formatter.Title("Commands")+":")
		self.FormatSubCommands(&output, formatter, screen_width)
		fmt.Fprintln(&output)
		format_with_indent(&output, "Get help for an individual command by running:", "", screen_width)
		fmt.Fprintln(&output, "   ", strings.TrimSpace(self.CommandStringForUsage()), formatter.Italic("command"), "-h")
	}

	group_titles, gmap := self.GetVisibleOptions()
	if len(group_titles) > 0 {
		fmt.Fprintln(&output)
		fmt.Fprintln(&output, formatter.Title("Options")+":")
		for _, title := range group_titles {
			fmt.Fprintln(&output)
			if title != "" {
				fmt.Fprintln(&output, formatter.Title(title))
			}
			for _, opt := range gmap[title] {
				opt.FormatOption(&output, formatter, screen_width)
				fmt.Fprintln(&output)
			}
		}
	}
	output_text := output.String()
	// fmt.Printf("%#v\n", output_text)
	if formatter.EscapeCodesAllowed() {
		pager := exec.Command(kitty.DefaultPager[0], kitty.DefaultPager[1:]...)
		pager.Stdin = strings.NewReader(output_text)
		pager.Stdout = os.Stdout
		pager.Stderr = os.Stderr
		pager.Run()
	} else {
		os.Stdout.Write([]byte(output_text))
	}
}
