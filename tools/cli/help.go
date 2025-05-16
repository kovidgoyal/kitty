// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"slices"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
)

var _ = fmt.Print

func ShowError(err error) {
	formatter := markup.New(tty.IsTerminal(os.Stderr.Fd()))
	msg := formatter.Prettify(err.Error())
	fmt.Fprintln(os.Stderr, formatter.Err("Error")+":", msg)
}

func (self *Command) version_string(formatter *markup.Context) string {
	return fmt.Sprintln(formatter.Italic(self.CommandStringForUsage()), formatter.Opt(kitty.VersionString), "created by", formatter.Title("Kovid Goyal"))
}

func (self *Command) ShowVersion() {
	formatter := markup.New(tty.IsTerminal(os.Stdout.Fd()))
	fmt.Fprint(os.Stdout, self.version_string(formatter))
}

func format_with_indent(output io.Writer, text string, indent string, screen_width int) {
	indented := style.WrapText(text, screen_width, style.WrapOptions{Indent: indent, Ignore_lines_containing: "#placeholder_for_formatting#", Trim_whitespace: true})
	io.WriteString(output, indented)
	io.WriteString(output, "\n")
}

func (self *Command) FormatSubCommands(output io.Writer, formatter *markup.Context, screen_width int) {
	for _, g := range self.SubCommandGroups {
		if !g.HasVisibleSubCommands() {
			continue
		}
		title := g.Title
		if title == "" {
			title = "Commands"
		}
		fmt.Fprintln(output)
		fmt.Fprintln(output, formatter.Title(title)+":")
		for _, c := range g.SubCommands {
			if c.Hidden {
				continue
			}
			fmt.Fprintln(output, "  ", formatter.Opt(c.Name))
			format_with_indent(output, formatter.Prettify(c.ShortDescription), "    ", screen_width)
		}
	}

}

func (self *Option) FormatOptionForMan(output io.Writer) {
	fmt.Fprintln(output, ".TP")
	fmt.Fprint(output, ".BI \"")
	for i, a := range self.Aliases {
		fmt.Fprint(output, a.String())
		if i != len(self.Aliases)-1 {
			fmt.Fprint(output, ", ")
		}
	}
	fmt.Fprint(output, "\" ")
	defval := self.Default
	switch self.OptionType {
	case CountOption:
		defval = ""
	case BoolOption:
		defval = utils.IfElse(self.Default == "true", "yes", "no")
	}

	if defval != "" {
		fmt.Fprintf(output, "\" [=%s]\"", escape_text_for_man(defval))
	}
	fmt.Fprintln(output)
	fmt.Fprintln(output, escape_help_for_man(self.Help))
	if self.Choices != nil {
		fmt.Fprintln(output)
		fmt.Fprintln(output, "Choices: "+strings.Join(self.Choices, ", "))
	}
}

func (self *Option) FormatOption(output io.Writer, formatter *markup.Context, screen_width int) {
	fmt.Fprint(output, "  ")
	for i, a := range self.Aliases {
		fmt.Fprint(output, formatter.Opt(a.String()))
		if i != len(self.Aliases)-1 {
			fmt.Fprint(output, ", ")
		}
	}
	defval := self.Default
	switch self.OptionType {
	case CountOption:
		defval = ""
	case BoolOption:
		yn := utils.IfElse(self.Default == "true", "yes", "no")
		fmt.Fprintf(output, " %s", formatter.Italic("[="+yn+"]"))
		defval = ""
	}
	if defval != "" {
		fmt.Fprintf(output, " [=%s]", formatter.Italic(defval))
	}
	fmt.Fprintln(output)
	format_with_indent(output, formatter.Prettify(prepare_help_text_for_display(self.Help)), "    ", screen_width)
	if self.Choices != nil {
		format_with_indent(output, "Choices: "+strings.Join(self.Choices, ", "), "    ", screen_width)
	}
}

func (self *Command) ShowHelp() {
	self.ShowHelpWithCommandString(strings.TrimSpace(self.CommandStringForUsage()))
}

func ShowHelpInPager(text string) {
	pager := exec.Command(kitty.DefaultPager[0], kitty.DefaultPager[1:]...)
	pager.Stdin = strings.NewReader(text)
	pager.Stdout = os.Stdout
	pager.Stderr = os.Stderr
	_ = pager.Run()
}

func getDeterministicTimestamp() time.Time {
	if epoch, err := strconv.ParseInt(os.Getenv("SOURCE_DATE_EPOCH"), 10, 64); err == nil {
		return time.Unix(epoch, 0).UTC()
	}
	return time.Now()
}

func (self *Command) GenerateManPages(level int, recurse bool) (err error) {
	var names []string
	p := self
	for p != nil {
		names = append(names, p.Name)
		p = p.Parent
	}
	slices.Reverse(names)
	name := strings.Join(names, "-")
	outf, err := os.Create(fmt.Sprintf("%s.%d", name, level))
	if err != nil {
		return err
	}
	defer outf.Close()
	fmt.Fprintf(outf, `.TH "%s" "1" "%s" "%s" "%s"`, name, getDeterministicTimestamp().Format("Jan 02, 2006"), kitty.VersionString, "kitten Manual")
	fmt.Fprintln(outf)
	fmt.Fprintln(outf, ".SH Name")
	fmt.Fprintln(outf, name, "\\-", escape_text_for_man(self.ShortDescription))
	fmt.Fprintln(outf, ".SH Usage")
	fmt.Fprintln(outf, ".SY", `"`+self.CommandStringForUsage()+` `+self.Usage+`"`)
	fmt.Fprintln(outf, ".YS")
	if self.HelpText != "" {
		fmt.Fprintln(outf, ".SH Description")
		fmt.Fprintln(outf, escape_help_for_man(self.HelpText))
	}

	if self.HasVisibleSubCommands() {
		for _, g := range self.SubCommandGroups {
			if !g.HasVisibleSubCommands() {
				continue
			}
			title := g.Title
			if title == "" {
				title = "Commands"
			}
			fmt.Fprintln(outf, ".SH", title)

			for _, c := range utils.Sort(g.SubCommands, func(a, b *Command) int { return strings.Compare(a.Name, b.Name) }) {
				if c.Hidden {
					continue
				}
				if recurse {
					if err = c.GenerateManPages(level, recurse); err != nil {
						return err
					}
				}
				fmt.Fprintln(outf, ".TP", "2")
				fmt.Fprintln(outf, c.Name)
				fmt.Fprintln(outf, escape_text_for_man(c.ShortDescription)+".", "See: ")
				fmt.Fprintf(outf, ".MR %s %d\n", name+"-"+c.Name, level)
			}
		}
		fmt.Fprintln(outf, ".PP")
		fmt.Fprintln(outf, "Get help for an individual command by running:")
		fmt.Fprintln(outf, ".SY", self.CommandStringForUsage())
		fmt.Fprintln(outf, "command", "-h")
		fmt.Fprintln(outf, ".YS")
	}

	group_titles, gmap := self.GetVisibleOptions()
	if len(group_titles) > 0 {
		for _, title := range group_titles {
			ptitle := title
			if title == "" {
				ptitle = "Options"
			}
			fmt.Fprintln(outf, ".SH", ptitle)
			for _, opt := range gmap[title] {
				opt.FormatOptionForMan(outf)
			}
		}
	}

	return
}

func (self *Command) ShowHelpWithCommandString(cs string) {
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

	fmt.Fprintln(&output, formatter.Title("Usage")+":", formatter.Exe(cs), strings.TrimSpace(formatter.Prettify(self.Usage)))
	fmt.Fprintln(&output)
	if self.HelpText != "" {
		format_with_indent(&output, formatter.Prettify(prepare_help_text_for_display(self.HelpText)), "", screen_width)
	} else if self.ShortDescription != "" {
		format_with_indent(&output, formatter.Prettify(self.ShortDescription), "", screen_width)
	}

	if self.HasVisibleSubCommands() {
		self.FormatSubCommands(&output, formatter, screen_width)
		fmt.Fprintln(&output)
		format_with_indent(&output, "Get help for an individual command by running:", "", screen_width)
		fmt.Fprintln(&output, "   ", strings.TrimSpace(self.CommandStringForUsage()), formatter.Italic("command"), "-h")
	}

	group_titles, gmap := self.GetVisibleOptions()
	if len(group_titles) > 0 {
		fmt.Fprintln(&output)
		for _, title := range group_titles {
			ptitle := title
			if title == "" {
				ptitle = "Options"
			}
			fmt.Fprintln(&output, formatter.Title(ptitle)+":")
			for _, opt := range gmap[title] {
				opt.FormatOption(&output, formatter, screen_width)
				fmt.Fprintln(&output)
			}
		}
	}
	output.WriteString(self.version_string(formatter))
	output_text := output.String()
	// fmt.Printf("%#v\n", output_text)
	if formatter.EscapeCodesAllowed() {
		ShowHelpInPager(output_text)
	} else {
		os.Stdout.WriteString(output_text)
	}
}
