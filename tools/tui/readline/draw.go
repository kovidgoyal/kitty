// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"
	"kitty/tools/wcswidth"
)

var _ = fmt.Print

func (self *Readline) write_line_with_prompt(line, prompt string, screen_width int) int {
	self.loop.QueueWriteString(prompt)
	self.loop.QueueWriteString(line)
	w := wcswidth.Stringwidth(prompt) + wcswidth.Stringwidth(line)
	return w / screen_width
}

func (self *Readline) move_cursor_to_text_position(pos, screen_width int) int {
	num_of_lines := pos / screen_width
	if num_of_lines > 0 {
		self.loop.MoveCursorVertically(num_of_lines)
	}
	self.loop.QueueWriteString("\r")
	x := pos % screen_width
	self.loop.MoveCursorHorizontally(x)
	return num_of_lines
}

func (self *Readline) redraw() {
	if self.cursor_y > 0 {
		self.loop.MoveCursorVertically(-self.cursor_y)
	}
	self.loop.QueueWriteString("\r")
	self.loop.ClearToEndOfScreen()
	y := 0
	line_with_cursor := 0
	screen_size, err := self.loop.ScreenSize()
	if err != nil {
		screen_size.WidthCells = 80
		screen_size.HeightCells = 24
	}
	for i, line := range self.lines {
		p := self.prompt
		if i > 0 {
			p = self.continuation_prompt
		}
		num_lines := self.write_line_with_prompt(line, p, int(screen_size.WidthCells))
		if i == self.cursor_line {
			line_with_cursor = y
		}
		y += num_lines
	}
	self.loop.MoveCursorVertically(-y + line_with_cursor)
	line := self.lines[self.cursor_line]
	line_with_cursor += self.move_cursor_to_text_position(wcswidth.Stringwidth(line[:self.cursor_pos_in_line]), int(screen_size.WidthCells))
	self.cursor_y = line_with_cursor
}
