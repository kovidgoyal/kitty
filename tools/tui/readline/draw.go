// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"
	"kitty/tools/wcswidth"
)

var _ = fmt.Print

func (self *Readline) update_current_screen_size() {
	screen_size, err := self.loop.ScreenSize()
	if err != nil {
		screen_size.WidthCells = 80
		screen_size.HeightCells = 24
	}
	if screen_size.WidthCells < 1 {
		screen_size.WidthCells = 1
	}
	if screen_size.HeightCells < 1 {
		screen_size.HeightCells = 1
	}
	self.screen_width = int(screen_size.WidthCells)
}

type ScreenLine struct {
	ParentLineNumber, OffsetInParentLine, PromptLen int
	TextLengthInCells, CursorCell, CursorTextPos    int
	Text                                            string
}

func (self *Readline) get_screen_lines() []*ScreenLine {
	if self.screen_width == 0 {
		self.update_current_screen_size()
	}
	ans := make([]*ScreenLine, 0, len(self.lines))
	found_cursor := false
	cursor_at_start_of_next_line := false
	for i, line := range self.lines {
		plen := self.prompt_len
		if i > 0 {
			plen = self.continuation_prompt_len
		}
		offset := 0
		has_cursor := i == self.cursor.Y
		for is_first := true; is_first || offset < len(line); is_first = false {
			l, width := wcswidth.TruncateToVisualLengthWithWidth(line[offset:], self.screen_width-plen)
			sl := ScreenLine{
				ParentLineNumber: i, OffsetInParentLine: offset,
				PromptLen: plen, TextLengthInCells: width,
				CursorCell: -1, Text: l, CursorTextPos: -1,
			}
			if cursor_at_start_of_next_line {
				cursor_at_start_of_next_line = false
				sl.CursorCell = plen
				sl.CursorTextPos = 0
			}
			ans = append(ans, &sl)
			if has_cursor && !found_cursor && offset <= self.cursor.X && self.cursor.X <= offset+len(l) {
				found_cursor = true
				ctpos := self.cursor.X - offset
				ccell := plen + wcswidth.Stringwidth(l[:ctpos])
				if ccell >= self.screen_width {
					if offset+len(l) < len(line) || i < len(self.lines)-1 {
						cursor_at_start_of_next_line = true
					} else {
						ans = append(ans, &ScreenLine{ParentLineNumber: i, OffsetInParentLine: len(line)})
					}
				} else {
					sl.CursorTextPos = ctpos
					sl.CursorCell = ccell
				}
			}
			plen = 0
			offset += len(l)
		}
	}
	return ans
}

func (self *Readline) redraw() {
	if self.screen_width == 0 {
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
	cursor_x := -1
	cursor_y := 0
	move_cursor_up_by := 0
	self.loop.AllowLineWrapping(false)
	for i, sl := range self.get_screen_lines() {
		self.loop.QueueWriteString("\r")
		if i > 0 {
			self.loop.QueueWriteString("\n")
		}
		if sl.PromptLen > 0 {
			if i == 0 {
				self.loop.QueueWriteString(self.prompt)
			} else {
				self.loop.QueueWriteString(self.continuation_prompt)
			}
		}
		self.loop.QueueWriteString(sl.Text)
		if sl.CursorCell > -1 {
			cursor_x = sl.CursorCell
		} else if cursor_x > -1 {
			move_cursor_up_by++
		}
		cursor_y++
	}
	self.loop.AllowLineWrapping(true)
	self.loop.MoveCursorVertically(-move_cursor_up_by)
	self.loop.QueueWriteString("\r")
	self.loop.MoveCursorHorizontally(cursor_x)
	self.cursor_y = 0
	if cursor_y > 0 {
		self.cursor_y = cursor_y - 1
	}
}
