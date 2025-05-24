// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package hints

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"unicode"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

func convert_text(text string, cols int) string {
	lines := make([]string, 0, 64)
	empty_line := strings.Repeat("\x00", cols) + "\n"
	s1 := utils.NewLineScanner(text)
	for s1.Scan() {
		full_line := s1.Text()
		if full_line == "" {
			lines = append(lines, empty_line)
			continue
		}
		if strings.TrimRight(full_line, "\r") == "" {
			for range len(full_line) {
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
	Match                []string         `json:"match"`
	Programs             []string         `json:"programs"`
	Multiple_joiner      string           `json:"multiple_joiner"`
	Customize_processing string           `json:"customize_processing"`
	Type                 string           `json:"type"`
	Groupdicts           []map[string]any `json:"groupdicts"`
	Extra_cli_args       []string         `json:"extra_cli_args"`
	Linenum_action       string           `json:"linenum_action"`
	Cwd                  string           `json:"cwd"`
}

func encode_hint(num int, alphabet string) (res string) {
	runes := []rune(alphabet)
	d := len(runes)
	for res == "" || num > 0 {
		res = string(runes[num%d]) + res
		num /= d
	}
	return
}

func decode_hint(x string, alphabet string) (ans int) {
	base := len(alphabet)
	index_map := make(map[rune]int, len(alphabet))
	for i, c := range alphabet {
		index_map[c] = i
	}
	for _, char := range x {
		ans = ans*base + index_map[char]
	}
	return
}

func as_rgb(c uint32) [3]float32 {
	return [3]float32{float32((c>>16)&255) / 255.0, float32((c>>8)&255) / 255.0, float32(c&255) / 255.0}
}

func hints_text_color(confval string) (ans string) {
	ans = confval
	if ans == "auto" {
		ans = "bright-gray"
		if bc, err := tui.ReadBasicColors(); err == nil {
			bg := as_rgb(bc.Background)
			c15 := as_rgb(bc.Color15)
			c8 := as_rgb(bc.Color8)
			if utils.RGBContrast(bg[0], bg[1], bg[2], c8[0], c8[1], c8[2]) > utils.RGBContrast(bg[0], bg[1], bg[2], c15[0], c15[1], c15[2]) {
				ans = "bright-black"
			}
		}
	}
	return
}

func main(_ *cli.Command, o *Options, args []string) (rc int, err error) {
	o.HintsTextColor = hints_text_color(o.HintsTextColor)
	output := tui.KittenOutputSerializer()
	if tty.IsTerminal(os.Stdin.Fd()) {
		return 1, fmt.Errorf("You must pass the text to be hinted on STDIN")
	}
	stdin, err := io.ReadAll(os.Stdin)
	if err != nil {
		return 1, fmt.Errorf("Failed to read from STDIN with error: %w", err)
	}
	if len(args) > 0 && o.CustomizeProcessing == "" && o.Type != "linenum" {
		return 1, fmt.Errorf("Extra command line arguments present: %s", strings.Join(args, " "))
	}
	input_text := parse_input(utils.UnsafeBytesToString(stdin))
	text, all_marks, index_map, err := find_marks(input_text, o, os.Args[2:]...)
	if err != nil {
		return 1, err
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
	window_title := o.WindowTitle
	if window_title == "" {
		switch o.Type {
		case "url":
			window_title = "Choose URL"
		default:
			window_title = "Choose text"
		}
	}
	current_text := ""
	current_input := ""
	match_suffix := ""
	switch o.AddTrailingSpace {
	case "always":
		match_suffix = " "
	case "never":
	default:
		if o.Multiple {
			match_suffix = " "
		}
	}
	chosen := []*Mark{}
	lp, err := loop.New(loop.NoAlternateScreen) // no alternate screen reduces flicker on exit
	if err != nil {
		return
	}
	fctx := style.Context{AllowEscapeCodes: true}
	faint := fctx.SprintFunc("dim")
	hint_style := fctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s bold", o.HintsForegroundColor, o.HintsBackgroundColor))
	text_style := fctx.SprintFunc(fmt.Sprintf("fg=%s bold", o.HintsTextColor))

	highlight_mark := func(m *Mark, mark_text string) string {
		hint := encode_hint(m.Index, alphabet)
		if current_input != "" && !strings.HasPrefix(hint, current_input) {
			return faint(mark_text)
		}
		hint = hint[len(current_input):]
		if hint == "" {
			hint = " "
		}
		if len(mark_text) <= len(hint) {
			mark_text = ""
		} else {
			replaced_text := mark_text[:len(hint)]
			replaced_text = strings.ReplaceAll(replaced_text, "\r", "\n")
			if strings.Contains(replaced_text, "\n") {
				buf := strings.Builder{}
				buf.Grow(2 * len(hint))
				h := hint
				parts := strings.Split(replaced_text, "\n")
				for i, x := range parts {
					if x != "" {
						buf.WriteString(h[:len(x)])
						h = h[len(x):]
					}
					if i != len(parts)-1 {
						buf.WriteString("\n")
					}
				}
				if h != "" {
					buf.WriteString(h)
				}
				hint = buf.String()
			}
			mark_text = mark_text[len(hint):]
		}
		ans := hint_style(hint) + text_style(mark_text)
		return fmt.Sprintf("\x1b]8;;mark:%d\a%s\x1b]8;;\a", m.Index, ans)
	}

	render := func() string {
		ans := text
		for i := len(all_marks) - 1; i >= 0; i-- {
			mark := &all_marks[i]
			if ignore_mark_indices.Has(mark.Index) {
				continue
			}
			mtext := highlight_mark(mark, ans[mark.Start:mark.End])
			ans = ans[:mark.Start] + mtext + ans[mark.End:]
		}
		ans = strings.ReplaceAll(ans, "\x00", "")
		return strings.TrimRightFunc(strings.NewReplacer("\r", "\r\n", "\n", "\r\n").Replace(ans), unicode.IsSpace)
	}

	draw_screen := func() {
		lp.StartAtomicUpdate()
		defer lp.EndAtomicUpdate()
		if current_text == "" {
			current_text = render()
		}
		lp.ClearScreen()
		lp.QueueWriteString(current_text)
	}
	reset := func() {
		current_input = ""
		current_text = ""
	}

	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		lp.SetWindowTitle(window_title)
		lp.AllowLineWrapping(false)
		draw_screen()
		lp.SendOverlayReady()
		return "", nil
	}
	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		return ""
	}
	lp.OnResize = func(old_size, new_size loop.ScreenSize) error {
		draw_screen()
		return nil
	}
	lp.OnRCResponse = func(data []byte) error {
		var r struct {
			Type string
			Mark int
		}
		if err := json.Unmarshal(data, &r); err != nil {
			return err
		}
		if r.Type == "mark_activated" {
			if m, ok := index_map[r.Mark]; ok {
				chosen = append(chosen, m)
				if o.Multiple {
					ignore_mark_indices.Add(m.Index)
					reset()
				} else {
					lp.Quit(0)
					return nil
				}

			}
		}
		return nil
	}

	lp.OnText = func(text string, _, _ bool) error {
		changed := false
		for _, ch := range text {
			if strings.ContainsRune(alphabet, ch) {
				current_input += string(ch)
				changed = true
			}
		}
		if changed {
			matches := []*Mark{}
			for idx, m := range index_map {
				if eh := encode_hint(idx, alphabet); strings.HasPrefix(eh, current_input) {
					matches = append(matches, m)
				}
			}
			if len(matches) == 1 {
				chosen = append(chosen, matches[0])
				if o.Multiple {
					ignore_mark_indices.Add(matches[0].Index)
					reset()
				} else {
					lp.Quit(0)
					return nil
				}
			}
			current_text = ""
			draw_screen()
		}
		return nil
	}

	lp.OnKeyEvent = func(ev *loop.KeyEvent) error {
		if ev.MatchesPressOrRepeat("backspace") {
			ev.Handled = true
			r := []rune(current_input)
			if len(r) > 0 {
				r = r[:len(r)-1]
				current_input = string(r)
				current_text = ""
			}
			draw_screen()
		} else if ev.MatchesPressOrRepeat("enter") || ev.MatchesPressOrRepeat("space") {
			ev.Handled = true
			if current_input != "" {
				idx := decode_hint(current_input, alphabet)
				if m := index_map[idx]; m != nil {
					chosen = append(chosen, m)
					ignore_mark_indices.Add(idx)
					if o.Multiple {
						reset()
						draw_screen()
					} else {
						lp.Quit(0)
					}
				} else {
					current_input = ""
					current_text = ""
					draw_screen()
				}
			}
		} else if ev.MatchesPressOrRepeat("esc") {
			if o.Multiple {
				lp.Quit(0)
			} else {
				lp.Quit(1)
			}
		}
		return nil
	}

	err = lp.Run()
	if err != nil {
		return 1, err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return 1, nil
	}
	if lp.ExitCode() != 0 {
		return lp.ExitCode(), nil
	}
	result.Match = make([]string, len(chosen))
	result.Groupdicts = make([]map[string]any, len(chosen))
	for i, m := range chosen {
		result.Match[i] = m.Text + match_suffix
		result.Groupdicts[i] = m.Groupdict
	}
	fmt.Println(output(result))
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
