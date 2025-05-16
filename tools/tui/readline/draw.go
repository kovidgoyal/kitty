// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
	"strings"
)

var _ = fmt.Print

func (self *Readline) update_current_screen_size() {
	var screen_size loop.ScreenSize
	var err error
	if self.loop != nil {
		screen_size, err = self.loop.ScreenSize()
		if err != nil {
			screen_size.WidthCells = 80
			screen_size.HeightCells = 24
		}
	} else {
		screen_size.WidthCells = 80
		screen_size.HeightCells = 24
	}
	self.screen_width = max(1, int(screen_size.WidthCells))
	self.screen_height = max(1, int(screen_size.HeightCells))
}

type ScreenLine struct {
	ParentLineNumber, OffsetInParentLine         int
	Prompt                                       Prompt
	TextLengthInCells, CursorCell, CursorTextPos int
	Text                                         string
	AfterLineBreak                               bool
}

func (self *Readline) format_arg_prompt(cna string) string {
	return fmt.Sprintf("(arg: %s) ", self.fmt_ctx.Yellow(cna))
}

func (self *Readline) prompt_for_line_number(i int) Prompt {
	is_line_with_cursor := i == self.input_state.cursor.Y
	if is_line_with_cursor && self.keyboard_state.current_numeric_argument != "" {
		return self.make_prompt(self.format_arg_prompt(self.keyboard_state.current_numeric_argument), i > 0)
	}
	if i == 0 {
		if self.history_search != nil {
			return self.make_prompt(self.history_search_prompt(), i > 0)
		}
		return self.prompt
	}
	return self.continuation_prompt
}

func (self *Readline) apply_syntax_highlighting() (lines []string, cursor Position) {
	highlighter := self.syntax_highlighted.highlighter
	highlighter_name := "default"
	if self.history_search != nil {
		highlighter = self.history_search_highlighter
		highlighter_name = "## history ##"
	}
	if highlighter == nil {
		return self.input_state.lines, self.input_state.cursor
	}
	src := strings.Join(self.input_state.lines, "\n")
	if len(self.syntax_highlighted.lines) > 0 && self.syntax_highlighted.last_highlighter_name == highlighter_name && self.syntax_highlighted.src_for_last_highlight == src {
		lines = self.syntax_highlighted.lines
	} else {
		if src == "" {
			lines = []string{""}
		} else {
			text := highlighter(src, self.input_state.cursor.X, self.input_state.cursor.Y)
			lines = utils.Splitlines(text)
			for len(lines) < len(self.input_state.lines) {
				lines = append(lines, "syntax highlighter malfunctioned")
			}
		}
	}
	line := lines[self.input_state.cursor.Y]
	w := wcswidth.Stringwidth(self.input_state.lines[self.input_state.cursor.Y][:self.input_state.cursor.X])
	x := len(wcswidth.TruncateToVisualLength(line, w))
	return lines, Position{X: x, Y: self.input_state.cursor.Y}
}

func (self *Readline) get_screen_lines() []*ScreenLine {
	if self.screen_width == 0 || self.screen_height == 0 {
		self.update_current_screen_size()
	}
	lines, cursor := self.apply_syntax_highlighting()
	ans := make([]*ScreenLine, 0, len(lines))
	found_cursor := false
	cursor_at_start_of_next_line := false
	for i, line := range lines {
		prompt := self.prompt_for_line_number(i)
		offset := 0
		has_cursor := i == cursor.Y
		for is_first := true; is_first || offset < len(line); is_first = false {
			l, width := wcswidth.TruncateToVisualLengthWithWidth(line[offset:], self.screen_width-prompt.Length)
			sl := ScreenLine{
				ParentLineNumber: i, OffsetInParentLine: offset,
				Prompt: prompt, TextLengthInCells: width,
				CursorCell: -1, Text: l, CursorTextPos: -1, AfterLineBreak: is_first,
			}
			if cursor_at_start_of_next_line {
				cursor_at_start_of_next_line = false
				sl.CursorCell = prompt.Length
				sl.CursorTextPos = 0
				found_cursor = true
			}
			ans = append(ans, &sl)
			if has_cursor && !found_cursor && offset <= cursor.X && cursor.X <= offset+len(l) {
				found_cursor = true
				ctpos := cursor.X - offset
				ccell := prompt.Length + wcswidth.Stringwidth(l[:ctpos])
				if ccell >= self.screen_width {
					if offset+len(l) < len(line) || i < len(lines)-1 {
						cursor_at_start_of_next_line = true
					} else {
						ans = append(ans, &ScreenLine{ParentLineNumber: i, OffsetInParentLine: len(line)})
					}
				} else {
					sl.CursorTextPos = ctpos
					sl.CursorCell = ccell
				}
			}
			prompt = Prompt{}
			offset += len(l)
		}
	}
	return ans
}

func (self *Readline) redraw() {
	if self.screen_width == 0 || self.screen_height == 0 {
		self.update_current_screen_size()
	}
	if self.screen_width < 4 {
		return
	}
	if self.cursor_y > 0 {
		self.loop.MoveCursorVertically(-self.cursor_y)
	}
	self.loop.QueueWriteString("\r")
	self.loop.ClearToEndOfScreen()
	prompt_lines := self.get_screen_lines()
	csl, csl_cached := self.completion_screen_lines()
	render_completion_above := len(csl)+len(prompt_lines) > self.screen_height
	completion_needs_render := len(csl) > 0 && (!render_completion_above || !self.completions.current.last_rendered_above || !csl_cached)
	final_cursor_x := -1
	cursor_y := 0
	move_cursor_up_by := 0

	render_completion_lines := func() int {
		if completion_needs_render {
			if render_completion_above {
				self.loop.QueueWriteString("\r")
			} else {
				self.loop.QueueWriteString("\r\n")
			}
			for i, cl := range csl {
				self.loop.QueueWriteString(cl)
				if i < len(csl)-1 || render_completion_above {
					self.loop.QueueWriteString("\n\r")
				}

			}
			return len(csl)
		}
		return 0
	}

	self.loop.AllowLineWrapping(false)
	if render_completion_above {
		render_completion_lines()
	}
	self.loop.AllowLineWrapping(true)
	self.loop.QueueWriteString("\r")
	text_length := 0

	for i, sl := range prompt_lines {
		cursor_moved_down := false
		if i > 0 && sl.AfterLineBreak {
			self.loop.QueueWriteString("\r\n")
			cursor_moved_down = true
			text_length = 0
		}
		if sl.Prompt.Length > 0 {
			p := self.prompt_for_line_number(i)
			self.loop.QueueWriteString(p.Text)
			text_length += p.Length
		}
		self.loop.QueueWriteString(sl.Text)
		text_length += sl.TextLengthInCells
		if text_length == self.screen_width && sl.Text == "" && i == len(prompt_lines)-1 {
			self.loop.QueueWriteString("\r\n")
			cursor_moved_down = true
			text_length = 0
		}
		if text_length > self.screen_width {
			cursor_moved_down = true
			text_length -= self.screen_width
		}
		if sl.CursorCell > -1 {
			final_cursor_x = sl.CursorCell
		} else if final_cursor_x > -1 {
			if cursor_moved_down {
				move_cursor_up_by++
			}
		}
		if cursor_moved_down {
			cursor_y++
		}
	}
	if !render_completion_above {
		move_cursor_up_by += render_completion_lines()
	}
	self.loop.MoveCursorVertically(-move_cursor_up_by)
	self.loop.QueueWriteString("\r")
	self.loop.MoveCursorHorizontally(final_cursor_x)
	self.cursor_y = 0
	cursor_y -= move_cursor_up_by
	if cursor_y > 0 {
		self.cursor_y = cursor_y
	}
}
