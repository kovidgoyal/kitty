// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ask

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
	"io"
	"os"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"
)

var _ = fmt.Print

type Choice struct {
	text          string
	idx           int
	color, letter string
}

func (self Choice) prefix() string {
	return string([]rune(self.text)[:self.idx])
}

func (self Choice) display_letter() string {
	return string([]rune(self.text)[self.idx])
}

func (self Choice) suffix() string {
	return string([]rune(self.text)[self.idx+1:])
}

type Range struct {
	start, end, y int
}

func (self *Range) has_point(x, y int) bool {
	return y == self.y && self.start <= x && x <= self.end
}

func truncate_at_space(text string, width int) (string, string) {
	truncated := wcswidth.TruncateToVisualLength(text, width)
	p := len(truncated)
	if p == len(text) {
		return text, ""
	}
	if p == 0 {
		// The first character is wider than width, consume it anyway so
		// that callers always make progress
		_, p = utf8.DecodeRuneInString(text)
	} else if i := strings.LastIndexByte(truncated, ' '); i > 0 && wcswidth.Stringwidth(truncated[i:]) < 12 {
		p = i + 1
	}
	return text[:p], text[p:]
}

func extra_for(width, screen_width int) int {
	return max(0, screen_width-width)/2 + 1
}

var debugprintln = tty.DebugPrintln
var _ = debugprintln

func GetChoices(o *Options) (response string, err error) {
	response = ""
	lp, err := loop.New()
	if err != nil {
		return "", err
	}
	lp.MouseTrackingMode(loop.FULL_MOUSE_TRACKING)

	prefix_style_pat := regexp.MustCompile("^(?:\x1b\\[[^m]*?m)+")
	choice_order := make([]Choice, 0, len(o.Choices))
	clickable_ranges := make(map[string][]Range, 16)
	allowed := utils.NewSet[string](max(2, len(o.Choices)))
	response_on_accept := o.Default
	switch o.Type {
	case "yesno":
		allowed.AddItems("y", "n")
		if !allowed.Has(response_on_accept) {
			response_on_accept = "y"
		}
	case "choices":
		first_choice := ""
		for i, x := range o.Choices {
			letter, text, _ := strings.Cut(x, ":")
			color := ""
			if strings.Contains(letter, ";") {
				letter, color, _ = strings.Cut(letter, ";")
			}
			letter = strings.ToLower(letter)
			idx := strings.Index(strings.ToLower(text), letter)
			if idx < 0 {
				return "", fmt.Errorf("The choice letter %#v is not present in the choice text: %#v", letter, text)
			}
			idx = len([]rune(strings.ToLower(text)[:idx]))
			allowed.Add(letter)
			c := Choice{text: text, idx: idx, color: color, letter: letter}
			choice_order = append(choice_order, c)
			if i == 0 {
				first_choice = letter
			}
		}
		if !allowed.Has(response_on_accept) {
			response_on_accept = first_choice
		}
	}
	message := o.Message
	hidden_text_start_pos := -1
	hidden_text_end_pos := -1
	hidden_text := ""
	m := markup.New(true)
	replacement_text := fmt.Sprintf("Press %s or click to show", m.Green(o.UnhideKey))
	var replacement_ranges []Range
	if message != "" && o.HiddenTextPlaceholder != "" {
		hidden_text_start_pos = strings.Index(message, o.HiddenTextPlaceholder)
		if hidden_text_start_pos > -1 {
			raw, err := io.ReadAll(os.Stdin)
			if err != nil {
				return "", fmt.Errorf("Failed to read hidden text from STDIN: %w", err)
			}
			hidden_text = strings.TrimRightFunc(utils.UnsafeBytesToString(raw), unicode.IsSpace)
			hidden_text_end_pos = hidden_text_start_pos + len(replacement_text)
			suffix := message[hidden_text_start_pos+len(o.HiddenTextPlaceholder):]
			message = message[:hidden_text_start_pos] + replacement_text + suffix
		}
	}

	// A layout is a block of rows that is rendered without line wrapping or
	// scrolling, with clickable ranges whose y co-ordinates are relative to the
	// first row of the block.
	type Layout struct {
		rows   []string
		ranges map[string][]Range
	}

	max_row_width := func(rows []string) (ans int) {
		for _, row := range rows {
			ans = max(ans, wcswidth.Stringwidth(row))
		}
		return
	}

	// Wrap text to fit in screen_width, returning the wrapped lines and the
	// ranges, relative to the returned lines, occupied by the bytes
	// text[hot_start:hot_end], which may be split over multiple lines.
	draw_long_text := func(screen_width int, text string, hot_start, hot_end int) (lines []string, hot_ranges []Range) {
		if screen_width < 3 {
			return
		}
		if text == "" {
			return []string{""}, nil
		}
		width := screen_width - 2
		prefix := prefix_style_pat.FindString(text)
		offset := 0
		for text != "" {
			var raw string
			raw, text = truncate_at_space(text, width)
			start := offset + len(raw) - len(strings.TrimLeftFunc(raw, unicode.IsSpace))
			offset += len(raw)
			t := strings.TrimSpace(raw)
			pad := extra_for(wcswidth.Stringwidth(t), width)
			if s, e := max(hot_start, start), min(hot_end, start+len(t)); s < e {
				if w := wcswidth.Stringwidth(t[s-start : e-start]); w > 0 {
					x := pad + wcswidth.Stringwidth(t[:s-start])
					hot_ranges = append(hot_ranges, Range{x, x + w - 1, len(lines)})
				}
			}
			lines = append(lines, strings.Repeat(" ", pad)+m.Bold(prefix+t))
		}
		return
	}

	ctx := style.Context{AllowEscapeCodes: true}

	layout_choice_boxes := func(screen_width int, choices ...Choice) Layout {
		ans := Layout{ranges: make(map[string][]Range, len(choices))}
		width := screen_width - 2
		current_line_length := 0
		type Item struct{ letter, text string }
		type Line = []Item
		var current_line Line
		lines := make([]Line, 0, 32)
		sep := "  "
		sep_sz := len(sep) + 2 // for the borders

		for _, choice := range choices {
			text := " " + choice.prefix()
			color := choice.color
			if choice.color == "" {
				color = "green"
			}
			text += ctx.SprintFunc("fg=" + color)(choice.display_letter())
			text += choice.suffix() + " "
			sz := wcswidth.Stringwidth(text)
			if len(current_line) > 0 && sz+sep_sz+current_line_length > width {
				lines = append(lines, current_line)
				current_line = nil
				current_line_length = 0
			}
			current_line = append(current_line, Item{choice.letter, text})
			current_line_length += sz + sep_sz
		}
		if len(current_line) > 0 {
			lines = append(lines, current_line)
		}

		highlight := func(text string) string {
			return m.Yellow(text)
		}

		top := func(text string, highlight_frame bool) (ans string) {
			ans = "╭" + strings.Repeat("─", wcswidth.Stringwidth(text)) + "╮"
			if highlight_frame {
				ans = highlight(ans)
			}
			return
		}

		middle := func(text string, highlight_frame bool) (ans string) {
			f := "│"
			if highlight_frame {
				f = highlight(f)
			}
			return f + text + f
		}

		bottom := func(text string, highlight_frame bool) (ans string) {
			ans = "╰" + strings.Repeat("─", wcswidth.Stringwidth(text)) + "╯"
			if highlight_frame {
				ans = highlight(ans)
			}
			return
		}

		add_row := func(add_borders func(string, bool) string, items ...Item) {
			type Position struct {
				letter  string
				x, size int
			}
			texts := make([]string, 0, 8)
			positions := make([]Position, 0, 8)
			x := 0
			for _, item := range items {
				text := item.text
				positions = append(positions, Position{item.letter, x, wcswidth.Stringwidth(text) + 2})
				text = add_borders(text, item.letter == response_on_accept)
				text += sep
				x += wcswidth.Stringwidth(text)
				texts = append(texts, text)
			}
			line := strings.TrimRightFunc(strings.Join(texts, ""), unicode.IsSpace)
			offset := extra_for(wcswidth.Stringwidth(line), width)
			y := len(ans.rows)
			for _, pos := range positions {
				x = pos.x + offset
				ans.ranges[pos.letter] = append(ans.ranges[pos.letter], Range{x, x + pos.size - 1, y})
			}
			ans.rows = append(ans.rows, strings.Repeat(" ", offset)+line)
		}
		for _, boxed_line := range lines {
			add_row(top, boxed_line...)
			add_row(middle, boxed_line...)
			add_row(bottom, boxed_line...)
		}
		return ans
	}

	layout_compact_yesno := func(screen_width int) Layout {
		yes := m.Green("Y") + "es"
		no := m.BrightRed("N") + "o"
		sep := strings.Repeat(" ", 3)
		text := yes + sep + no
		x := extra_for(wcswidth.Stringwidth(text), screen_width-2)
		nx := x + wcswidth.Stringwidth(yes) + len(sep)
		return Layout{
			rows: []string{strings.Repeat(" ", x) + text},
			ranges: map[string][]Range{
				"y": {{x, x + wcswidth.Stringwidth(yes) - 1, 0}},
				"n": {{nx, nx + wcswidth.Stringwidth(no) - 1, 0}},
			},
		}
	}

	layout_compact_choices := func(screen_width int) Layout {
		type Item struct {
			letter string
			size   int
		}
		ans := Layout{ranges: make(map[string][]Range, len(choice_order))}
		current_line := ""
		var current_items []Item
		width := screen_width - 2

		commit_line := func() {
			x := extra_for(wcswidth.Stringwidth(current_line), width)
			y := len(ans.rows)
			ans.rows = append(ans.rows, strings.Repeat(" ", x)+current_line)
			for _, item := range current_items {
				// size includes the two trailing separator spaces
				ans.ranges[item.letter] = append(ans.ranges[item.letter], Range{x, x + item.size - 3, y})
				x += item.size
			}
			current_items = current_items[:0]
			current_line = ""
		}
		for _, choice := range choice_order {
			text := choice.prefix()
			spec := ""
			if choice.color != "" {
				spec = "fg=" + choice.color
			} else {
				spec = "fg=green"
			}
			if choice.letter == response_on_accept {
				spec += " u=straight"
			}
			text += ctx.SprintFunc(spec)(choice.display_letter())
			text += choice.suffix()
			text += "  "
			sz := wcswidth.Stringwidth(text)
			if current_line != "" && sz+wcswidth.Stringwidth(current_line) >= width {
				commit_line()
			}
			current_line += text
			current_items = append(current_items, Item{choice.letter, sz})
		}
		if current_line != "" {
			commit_line()
		}
		return ans
	}

	draw_screen := func() error {
		lp.StartAtomicUpdate()
		defer lp.EndAtomicUpdate()
		lp.ClearScreen()
		sz, err := lp.ScreenSize()
		if err != nil {
			return err
		}
		screen_width, screen_height := int(sz.WidthCells), int(sz.HeightCells)
		var rows []string
		var unhide_ranges []Range
		if message != "" {
			scanner := utils.NewLineScanner(message)
			for scanner.Scan() {
				line := scanner.Text()
				hot_start, hot_end := -1, -1
				if hidden_text != "" {
					if idx := strings.Index(line, replacement_text); idx > -1 {
						hot_start, hot_end = idx, idx+len(replacement_text)
					}
				}
				lines, hot_ranges := draw_long_text(screen_width, line, hot_start, hot_end)
				for _, r := range hot_ranges {
					r.y += len(rows)
					unhide_ranges = append(unhide_ranges, r)
				}
				rows = append(rows, lines...)
			}
		}
		num_message_rows := len(rows)
		if screen_height > 2 {
			rows = append(rows, "")
		}
		var choices Layout
		switch o.Type {
		case "yesno":
			choices = layout_choice_boxes(screen_width, Choice{"Yes", 0, "green", "y"}, Choice{"No", 0, "red", "n"})
		case "choices":
			choices = layout_choice_boxes(screen_width, choice_order...)
		}
		if len(rows)+len(choices.rows) > screen_height || max_row_width(choices.rows) > screen_width {
			switch o.Type {
			case "yesno":
				choices = layout_compact_yesno(screen_width)
			case "choices":
				choices = layout_compact_choices(screen_width)
			}
		}
		choices_start := len(rows)
		rows = append(rows, choices.rows...)

		// Center the message vertically. If everything does not fit, align
		// the bottom of the content with the bottom of the screen so that the
		// choices remain visible, letting the top of the message go
		// off-screen.
		top := min(max(0, (screen_height-num_message_rows)/2-2), screen_height-len(rows))
		lp.AllowLineWrapping(false)
		defer lp.AllowLineWrapping(true)
		for i, row := range rows {
			if y := top + i; y >= 0 && y < screen_height {
				if wcswidth.Stringwidth(row) > screen_width {
					// Rows can only be too wide when a single choice does not
					// fit, indicate that it has been truncated
					row = wcswidth.TruncateToVisualLength(row, screen_width-1) + "…"
				}
				lp.MoveCursorTo(1, y+1)
				lp.QueueWriteString(row)
			}
		}

		on_screen := func(r Range, offset int) (Range, bool) {
			r.y += offset
			return r, r.y >= 0 && r.y < screen_height
		}
		clickable_ranges = make(map[string][]Range, len(choices.ranges))
		for letter, ranges := range choices.ranges {
			for _, r := range ranges {
				if r, ok := on_screen(r, top+choices_start); ok {
					clickable_ranges[letter] = append(clickable_ranges[letter], r)
				}
			}
		}
		replacement_ranges = replacement_ranges[:0]
		for _, r := range unhide_ranges {
			if r, ok := on_screen(r, top); ok {
				replacement_ranges = append(replacement_ranges, r)
			}
		}
		return nil
	}

	unhide := func() {
		if hidden_text != "" && message != "" {
			message = message[:hidden_text_start_pos] + hidden_text + message[hidden_text_end_pos:]
			hidden_text = ""
			_ = draw_screen()
		}
	}

	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		if o.Title != "" {
			lp.SetWindowTitle(o.Title)
		}
		return "", draw_screen()
	}

	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		return ""
	}

	lp.OnText = func(text string, from_key_event, in_bracketed_paste bool) error {
		text = strings.ToLower(text)
		if allowed.Has(text) {
			response = text
			lp.Quit(0)
		} else if hidden_text != "" && text == o.UnhideKey {
			unhide()
		} else if o.Type == "yesno" {
			lp.Quit(1)
		}
		return nil
	}

	lp.OnKeyEvent = func(ev *loop.KeyEvent) error {
		if ev.MatchesPressOrRepeat("esc") || ev.MatchesPressOrRepeat("ctrl+c") {
			ev.Handled = true
			lp.Quit(1)
		} else if ev.MatchesPressOrRepeat("enter") || ev.MatchesPressOrRepeat("kp_enter") {
			ev.Handled = true
			response = response_on_accept
			lp.Quit(0)
		}
		return nil
	}

	lp.OnMouseEvent = func(ev *loop.MouseEvent) error {
		on_letter := ""
		for letter, ranges := range clickable_ranges {
			for _, r := range ranges {
				if r.has_point(ev.Cell.X, ev.Cell.Y) {
					on_letter = letter
					break
				}
			}
		}
		if on_letter != "" {
			if s, has_shape := lp.CurrentPointerShape(); !has_shape && s != loop.POINTER_POINTER {
				lp.PushPointerShape(loop.POINTER_POINTER)
			}
		} else {
			if _, has_shape := lp.CurrentPointerShape(); has_shape {
				lp.PopPointerShape()
			}
		}

		if ev.Event_type == loop.MOUSE_CLICK {
			if on_letter != "" {
				response = on_letter
				lp.Quit(0)
				return nil
			}
			if hidden_text != "" {
				for _, r := range replacement_ranges {
					if r.has_point(ev.Cell.X, ev.Cell.Y) {
						unhide()
						break
					}
				}
			}
		}
		return nil
	}

	lp.OnResize = func(old, news loop.ScreenSize) error {
		return draw_screen()
	}

	err = lp.Run()
	if err != nil {
		return "", err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return "", fmt.Errorf("Filled by signal: %s", ds)
	}
	return response, nil
}
