// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package hints

import (
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	"kitty/tools/cli"
	"kitty/tools/tty"
	"kitty/tools/tui"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"kitty/tools/wcswidth"
)

var _ = fmt.Print

func convert_text(text string, cols int) string {
	lines := make([]string, 0, 64)
	empty_line := strings.Repeat("\x00", cols) + "\n"
	s1 := utils.NewLineScanner(text)
	for s1.Scan() {
		full_line := s1.Text()
		if full_line == "" {
			continue
		}
		if strings.TrimRight(full_line, "\r") == "" {
			for i := 0; i < len(full_line); i++ {
				lines = append(lines, empty_line)
			}
			continue
		}
		appended := false
		s2 := utils.NewSeparatorScanner(full_line, "\r")
		for s2.Scan() {
			line := s2.Text()
			if line != "" {
				line_sz := wcswidth.Stringwidth(line)
				extra := cols - line_sz
				if extra > 0 {
					line += strings.Repeat("\x00", extra)
				}
				lines = append(lines, line)
				lines = append(lines, "\r")
				appended = true
			}
		}
		if appended {
			lines[len(lines)-1] = "\n"
		}
	}
	ans := strings.Join(lines, "")
	return strings.TrimRight(ans, "\r\n")
}

func parse_input(text string) string {
	cols, err := strconv.Atoi(os.Getenv("OVERLAID_WINDOW_COLS"))
	if err == nil {
		return convert_text(text, cols)
	}
	term, err := tty.OpenControllingTerm()
	if err == nil {
		sz, err := term.GetSize()
		term.Close()
		if err == nil {
			return convert_text(text, int(sz.Col))
		}
	}
	return convert_text(text, 80)
}

type Result struct {
	Match                []string            `json:"match"`
	Programs             []string            `json:"programs"`
	Multiple_joiner      string              `json:"multiple_joiner"`
	Customize_processing string              `json:"customize_processing"`
	Type                 string              `json:"type"`
	Groupdicts           []map[string]string `json:"groupdicts"`
	Extra_cli_args       []string            `json:"extra_cli_args"`
	Linenum_action       string              `json:"linenum_action"`
	Cwd                  string              `json:"cwd"`
}

func main(_ *cli.Command, o *Options, args []string) (rc int, err error) {
	output := tui.KittenOutputSerializer()
	if tty.IsTerminal(os.Stdin.Fd()) {
		tui.ReportError(fmt.Errorf("You must pass the text to be hinted on STDIN"))
		return 1, nil
	}
	stdin, err := io.ReadAll(os.Stdin)
	if err != nil {
		tui.ReportError(fmt.Errorf("Failed to read from STDIN with error: %w", err))
		return 1, nil
	}
	if len(args) > 0 && o.CustomizeProcessing == "" && o.Type != "linenum" {
		tui.ReportError(fmt.Errorf("Extra command line arguments present: %s", strings.Join(args, " ")))
		return 1, nil
	}
	text := parse_input(utils.UnsafeBytesToString(stdin))
	all_marks, index_map, err := find_marks(text, o)
	if err != nil {
		tui.ReportError(err)
		return 1, nil
	}

	result := Result{
		Programs: o.Program, Multiple_joiner: o.MultipleJoiner, Customize_processing: o.CustomizeProcessing, Type: o.Type,
		Extra_cli_args: args, Linenum_action: o.LinenumAction,
	}
	result.Cwd, _ = os.Getwd()
	alphabet := o.Alphabet
	if alphabet == "" {
		alphabet = DEFAULT_HINT_ALPHABET
	}
	ignore_mark_indices := utils.NewSet[int](8)
	_, _, _ = all_marks, index_map, ignore_mark_indices
	window_title := o.WindowTitle
	if window_title == "" {
		switch o.Type {
		case "url":
			window_title = "Choose URL"
		default:
			window_title = "Choose text"
		}
	}
	lp, err := loop.New(loop.NoAlternateScreen) // no alternate screen reduces flicker on exit
	if err != nil {
		return
	}
	lp.OnInitialize = func() (string, error) {
		lp.SendOverlayReady()
		lp.SetCursorVisible(false)
		lp.SetWindowTitle(window_title)
		lp.AllowLineWrapping(false)
		return "", nil
	}
	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		return ""
	}

	output(result)
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
