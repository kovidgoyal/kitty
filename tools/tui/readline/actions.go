// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"
	"io"
	"strings"

	"kitty/tools/utils"
	"kitty/tools/wcswidth"
)

var _ = fmt.Print

func (self *Readline) text_upto_cursor_pos() string {
	buf := strings.Builder{}
	buf.Grow(1024)
	for i, line := range self.lines {
		if i == self.cursor.Y {
			buf.WriteString(line[:self.cursor.X])
			break
		} else {
			buf.WriteString(line)
			buf.WriteString("\n")
		}
	}
	return buf.String()
}

func (self *Readline) text_after_cursor_pos() string {
	buf := strings.Builder{}
	buf.Grow(1024)
	for i, line := range self.lines {
		if i == self.cursor.Y {
			buf.WriteString(line[self.cursor.X:])
			buf.WriteString("\n")
		} else if i > self.cursor.Y {
			buf.WriteString(line)
			buf.WriteString("\n")
		}
	}
	ans := buf.String()
	ans = ans[:len(ans)-1]
	return ans
}

func (self *Readline) all_text() string {
	return strings.Join(self.lines, "\n")
}

func (self *Readline) add_text(text string) {
	new_lines := make([]string, 0, len(self.lines)+4)
	new_lines = append(new_lines, self.lines[:self.cursor.Y]...)
	var lines_after []string
	if len(self.lines) > self.cursor.Y+1 {
		lines_after = self.lines[self.cursor.Y+1:]
	}
	has_trailing_newline := strings.HasSuffix(text, "\n")

	add_line_break := func(line string) {
		new_lines = append(new_lines, line)
		self.cursor.X = len(line)
		self.cursor.Y += 1
	}
	cline := self.lines[self.cursor.Y]
	before_first_line := cline[:self.cursor.X]
	after_first_line := ""
	if self.cursor.X < len(cline) {
		after_first_line = cline[self.cursor.X:]
	}
	for i, line := range utils.Splitlines(text) {
		if i > 0 {
			add_line_break(line)
		} else {
			line := before_first_line + line
			self.cursor.X = len(line)
			new_lines = append(new_lines, line)
		}
	}
	if has_trailing_newline {
		add_line_break("")
	}
	if after_first_line != "" {
		if len(new_lines) == 0 {
			new_lines = append(new_lines, "")
		}
		new_lines[len(new_lines)-1] += after_first_line
	}
	if len(lines_after) > 0 {
		new_lines = append(new_lines, lines_after...)
	}
	self.lines = new_lines
}

func (self *Readline) move_cursor_left(amt uint, traverse_line_breaks bool) uint {
	var amt_moved uint
	for ; amt > 0; amt -= 1 {
		if self.cursor.X == 0 {
			if !traverse_line_breaks || self.cursor.Y == 0 {
				return amt_moved
			}
			self.cursor.Y -= 1
			self.cursor.X = len(self.lines[self.cursor.Y])
			amt_moved += 1
			continue
		}
		// This is an extremely inefficient algorithm but it does not matter since
		// lines are not large.
		line := self.lines[self.cursor.Y]
		runes := []rune(line[:self.cursor.X])
		orig_width := wcswidth.Stringwidth(line[:self.cursor.X])
		current_width := orig_width
		for current_width == orig_width && len(runes) > 0 {
			runes = runes[:len(runes)-1]
			s := string(runes)
			current_width = wcswidth.Stringwidth(s)
		}
		self.cursor.X = len(string(runes))
		amt_moved += 1
	}
	return amt_moved
}

func (self *Readline) move_cursor_right(amt uint, traverse_line_breaks bool) uint {
	var amt_moved uint
	for ; amt > 0; amt -= 1 {
		line := self.lines[self.cursor.Y]
		if self.cursor.X >= len(line) {
			if !traverse_line_breaks || self.cursor.Y == len(self.lines)-1 {
				return amt_moved
			}
			self.cursor.Y += 1
			self.cursor.X = 0
			amt_moved += 1
			continue
		}
		// This is an extremely inefficient algorithm but it does not matter since
		// lines are not large.
		before_runes := []rune(line[:self.cursor.X])
		after_runes := []rune(line[self.cursor.X:])
		orig_width := wcswidth.Stringwidth(line[:self.cursor.X])
		current_width := orig_width
		for current_width == orig_width && len(after_runes) > 0 {
			before_runes = append(before_runes, after_runes[0])
			current_width = wcswidth.Stringwidth(string(before_runes))
			after_runes = after_runes[1:]
		}
		// soak up any more runes that dont affect width
		for len(after_runes) > 0 {
			q := append(before_runes, after_runes[0])
			w := wcswidth.Stringwidth(string(q))
			if w != current_width {
				break
			}
			after_runes = after_runes[1:]
			before_runes = q
		}
		self.cursor.X = len(string(before_runes))
		amt_moved += 1
	}
	return amt_moved
}

func (self *Readline) move_to_start_of_line() bool {
	if self.cursor.X > 0 {
		self.cursor.X = 0
		return true
	}
	return false
}

func (self *Readline) move_to_end_of_line() bool {
	line := self.lines[self.cursor.Y]
	if self.cursor.X >= len(line) {
		return false
	}
	self.cursor.X = len(line)
	return true
}

func (self *Readline) move_to_start() bool {
	if self.cursor.Y == 0 && self.cursor.X == 0 {
		return false
	}
	self.cursor.Y = 0
	self.move_to_start_of_line()
	return true
}

func (self *Readline) move_to_end() bool {
	line := self.lines[self.cursor.Y]
	if self.cursor.Y == len(self.lines)-1 && self.cursor.X >= len(line) {
		return false
	}
	self.cursor.Y = len(self.lines) - 1
	self.move_to_end_of_line()
	return true
}

func (self *Readline) erase_between(start, end Position) {
	if end.Less(start) {
		start, end = end, start
	}
	if start.Y == end.Y {
		line := self.lines[start.Y]
		self.lines[start.Y] = line[:start.X] + line[end.X:]
		if self.cursor.Y == start.Y && self.cursor.X >= start.X {
			if self.cursor.X < end.X {
				self.cursor.X = start.X
			} else {
				self.cursor.X -= end.X - start.X
			}
		}
		return
	}
	lines := make([]string, 0, len(self.lines))
	for i, line := range self.lines {
		if i < start.Y || i > end.Y {
			lines = append(lines, line)
		} else if i == start.Y {
			lines = append(lines, line[:start.X])
			if self.cursor.Y == i && self.cursor.X > start.X {
				self.cursor.X = start.X
			}
		} else if i == end.Y {
			lines[len(lines)-1] += line[end.X:]
			if i == self.cursor.Y {
				self.cursor.Y = start.Y
				if self.cursor.X < end.X {
					self.cursor.X = start.X
				} else {
					self.cursor.X -= end.X - start.X
				}
			}
		} else if i == self.cursor.Y {
			self.cursor = start
		}
	}
	self.lines = lines
}

func (self *Readline) erase_chars_before_cursor(amt uint, traverse_line_breaks bool) uint {
	pos := self.cursor
	num := self.move_cursor_left(amt, traverse_line_breaks)
	if num == 0 {
		return num
	}
	self.erase_between(self.cursor, pos)
	return num
}

func (self *Readline) erase_chars_after_cursor(amt uint, traverse_line_breaks bool) uint {
	pos := self.cursor
	num := self.move_cursor_right(amt, traverse_line_breaks)
	if num == 0 {
		return num
	}
	self.erase_between(pos, self.cursor)
	return num
}

func (self *Readline) next_word_char_pos(traverse_line_breaks bool) int {
	return 0
}

func (self *Readline) perform_action(ac Action, repeat_count uint) error {
	switch ac {
	case ActionBackspace:
		if self.erase_chars_before_cursor(repeat_count, true) > 0 {
			return nil
		}
	case ActionDelete:
		if self.erase_chars_after_cursor(repeat_count, true) > 0 {
			return nil
		}
	case ActionMoveToStartOfLine:
		if self.move_to_start_of_line() {
			return nil
		}
	case ActionMoveToEndOfLine:
		if self.move_to_end_of_line() {
			return nil
		}
	case ActionMoveToStartOfDocument:
		if self.move_to_start() {
			return nil
		}
	case ActionMoveToEndOfDocument:
		if self.move_to_end() {
			return nil
		}
	case ActionCursorLeft:
		if self.move_cursor_left(repeat_count, true) > 0 {
			return nil
		}
	case ActionCursorRight:
		if self.move_cursor_right(repeat_count, true) > 0 {
			return nil
		}
	case ActionEndInput:
		line := self.lines[self.cursor.Y]
		if line == "" {
			return io.EOF
		}
		return self.perform_action(ActionAcceptInput, 1)
	case ActionAcceptInput:
		return ErrAcceptInput
	}
	return ErrCouldNotPerformAction
}
