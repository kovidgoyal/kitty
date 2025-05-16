// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"
	"io"
	"strings"
	"unicode"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

func (self *Readline) text_upto_cursor_pos() string {
	buf := strings.Builder{}
	buf.Grow(1024)
	for i, line := range self.input_state.lines {
		if i == self.input_state.cursor.Y {
			buf.WriteString(line[:min(len(line), self.input_state.cursor.X)])
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
	for i, line := range self.input_state.lines {
		if i == self.input_state.cursor.Y {
			buf.WriteString(line[min(len(line), self.input_state.cursor.X):])
			buf.WriteString("\n")
		} else if i > self.input_state.cursor.Y {
			buf.WriteString(line)
			buf.WriteString("\n")
		}
	}
	ans := buf.String()
	if ans != "" {
		ans = ans[:len(ans)-1]
	}
	return ans
}

func (self *Readline) all_text() string {
	return strings.Join(self.input_state.lines, "\n")
}

func (self *Readline) set_text(text string) {
	self.move_to_start()
	self.erase_chars_after_cursor(123456789, true)
	if text != "" {
		self.add_text(text)
	}
	self.move_to_end()
}

func (self *Readline) add_text(text string) {
	new_lines := make([]string, 0, len(self.input_state.lines)+4)
	new_lines = append(new_lines, self.input_state.lines[:self.input_state.cursor.Y]...)
	var lines_after []string
	if len(self.input_state.lines) > self.input_state.cursor.Y+1 {
		lines_after = self.input_state.lines[self.input_state.cursor.Y+1:]
	}
	has_trailing_newline := strings.HasSuffix(text, "\n")

	add_line_break := func(line string) {
		new_lines = append(new_lines, line)
		self.input_state.cursor.X = len(line)
		self.input_state.cursor.Y += 1
	}
	cline := self.input_state.lines[self.input_state.cursor.Y]
	before_first_line := cline[:self.input_state.cursor.X]
	after_first_line := ""
	if self.input_state.cursor.X < len(cline) {
		after_first_line = cline[self.input_state.cursor.X:]
	}
	for i, line := range utils.Splitlines(text) {
		if i > 0 {
			add_line_break(line)
		} else {
			line := before_first_line + line
			self.input_state.cursor.X = len(line)
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
	self.input_state.lines = new_lines
}

func (self *Readline) move_cursor_left(amt uint, traverse_line_breaks bool) (amt_moved uint) {
	for amt_moved < amt {
		if self.input_state.cursor.X == 0 {
			if !traverse_line_breaks || self.input_state.cursor.Y == 0 {
				return amt_moved
			}
			self.input_state.cursor.Y -= 1
			self.input_state.cursor.X = len(self.input_state.lines[self.input_state.cursor.Y])
			amt_moved++
			continue
		}
		line := self.input_state.lines[self.input_state.cursor.Y]
		for ci := wcswidth.NewCellIterator(line[:self.input_state.cursor.X]).GotoEnd(); amt_moved < amt && ci.Backward(); amt_moved++ {
			self.input_state.cursor.X -= len(ci.Current())
		}
	}
	return amt_moved
}

func (self *Readline) move_cursor_right(amt uint, traverse_line_breaks bool) (amt_moved uint) {
	for amt_moved < amt {
		line := self.input_state.lines[self.input_state.cursor.Y]
		if self.input_state.cursor.X >= len(line) {
			if !traverse_line_breaks || self.input_state.cursor.Y == len(self.input_state.lines)-1 {
				return amt_moved
			}
			self.input_state.cursor.Y += 1
			self.input_state.cursor.X = 0
			amt_moved++
			continue
		}

		for ci := wcswidth.NewCellIterator(line[self.input_state.cursor.X:]); amt_moved < amt && ci.Forward(); amt_moved++ {
			self.input_state.cursor.X += len(ci.Current())
		}
	}
	return amt_moved
}

func (self *Readline) move_cursor_to_target_line(source_line, target_line *ScreenLine) {
	if source_line != target_line {
		visual_distance_into_text := source_line.CursorCell - source_line.Prompt.Length
		self.input_state.cursor.Y = target_line.ParentLineNumber
		tp := wcswidth.TruncateToVisualLength(target_line.Text, visual_distance_into_text)
		self.input_state.cursor.X = target_line.OffsetInParentLine + len(tp)
	}
}

func (self *Readline) move_cursor_vertically(amt int) (ans int) {
	if self.screen_width == 0 {
		self.update_current_screen_size()
	}
	screen_lines := self.get_screen_lines()
	cursor_line_num := 0
	for i, sl := range screen_lines {
		if sl.CursorCell > -1 {
			cursor_line_num = i
			break
		}
	}
	target_line_num := min(max(0, cursor_line_num+amt), len(screen_lines)-1)
	ans = target_line_num - cursor_line_num
	if ans != 0 {
		self.move_cursor_to_target_line(screen_lines[cursor_line_num], screen_lines[target_line_num])
	}
	return ans
}

func (self *Readline) move_cursor_down(amt uint) uint {
	ans := uint(0)
	if self.screen_width == 0 {
		self.update_current_screen_size()
	}
	return ans
}

func (self *Readline) move_to_start_of_line() bool {
	if self.input_state.cursor.X > 0 {
		self.input_state.cursor.X = 0
		return true
	}
	return false
}

func (self *Readline) move_to_end_of_line() bool {
	line := self.input_state.lines[self.input_state.cursor.Y]
	if self.input_state.cursor.X >= len(line) {
		return false
	}
	self.input_state.cursor.X = len(line)
	return true
}

func (self *Readline) move_to_start() bool {
	if self.input_state.cursor.Y == 0 && self.input_state.cursor.X == 0 {
		return false
	}
	self.input_state.cursor.Y = 0
	self.move_to_start_of_line()
	return true
}

func (self *Readline) move_to_end() bool {
	line := self.input_state.lines[self.input_state.cursor.Y]
	if self.input_state.cursor.Y == len(self.input_state.lines)-1 && self.input_state.cursor.X >= len(line) {
		return false
	}
	self.input_state.cursor.Y = len(self.input_state.lines) - 1
	self.move_to_end_of_line()
	return true
}

func (self *Readline) erase_between(start, end Position) string {
	if end.Less(start) {
		start, end = end, start
	}
	buf := strings.Builder{}
	if start.Y == end.Y {
		line := self.input_state.lines[start.Y]
		buf.WriteString(line[start.X:end.X])
		self.input_state.lines[start.Y] = line[:start.X] + line[end.X:]
		if self.input_state.cursor.Y == start.Y && self.input_state.cursor.X >= start.X {
			if self.input_state.cursor.X < end.X {
				self.input_state.cursor.X = start.X
			} else {
				self.input_state.cursor.X -= end.X - start.X
			}
		}
		return buf.String()
	}
	lines := make([]string, 0, len(self.input_state.lines))
	for i, line := range self.input_state.lines {
		if i < start.Y || i > end.Y {
			lines = append(lines, line)
		} else if i == start.Y {
			lines = append(lines, line[:start.X])
			buf.WriteString(line[start.X:])
			if self.input_state.cursor.Y == i && self.input_state.cursor.X > start.X {
				self.input_state.cursor.X = start.X
			}
		} else if i == end.Y {
			lines[len(lines)-1] += line[end.X:]
			buf.WriteString(line[:end.X])
			if i == self.input_state.cursor.Y {
				self.input_state.cursor.Y = start.Y
				if self.input_state.cursor.X < end.X {
					self.input_state.cursor.X = start.X
				} else {
					self.input_state.cursor.X -= end.X - start.X
				}
			}
		} else {
			if i == self.input_state.cursor.Y {
				self.input_state.cursor = start
			}
			buf.WriteString(line)
			buf.WriteString("\n")
		}
	}
	self.input_state.lines = lines
	return buf.String()
}

func (self *Readline) erase_chars_before_cursor(amt uint, traverse_line_breaks bool) uint {
	pos := self.input_state.cursor
	num := self.move_cursor_left(amt, traverse_line_breaks)
	if num == 0 {
		return num
	}
	self.erase_between(self.input_state.cursor, pos)
	return num
}

func (self *Readline) erase_chars_after_cursor(amt uint, traverse_line_breaks bool) uint {
	pos := self.input_state.cursor
	num := self.move_cursor_right(amt, traverse_line_breaks)
	if num == 0 {
		return num
	}
	self.erase_between(pos, self.input_state.cursor)
	return num
}

func has_word_chars(text string) bool {
	for _, ch := range text {
		if unicode.IsLetter(ch) || unicode.IsDigit(ch) {
			return true
		}
	}
	return false
}

func (self *Readline) move_to_end_of_word(amt uint, traverse_line_breaks bool, is_part_of_word func(string) bool) (num_of_words_moved uint) {
	if amt == 0 {
		return 0
	}
	line := self.input_state.lines[self.input_state.cursor.Y]
	in_word := false
	ci := wcswidth.NewCellIterator(line[self.input_state.cursor.X:])
	sz := 0

	for ci.Forward() {
		current_is_word_char := is_part_of_word(ci.Current())
		plen := sz
		sz += len(ci.Current())
		if current_is_word_char {
			in_word = true
		} else if in_word {
			self.input_state.cursor.X += plen
			amt--
			num_of_words_moved++
			if amt == 0 {
				return
			}
			in_word = false
		}
	}
	if self.move_to_end_of_line() {
		amt--
		num_of_words_moved++
	}
	if amt > 0 {
		if traverse_line_breaks && self.input_state.cursor.Y < len(self.input_state.lines)-1 {
			self.input_state.cursor.Y++
			self.input_state.cursor.X = 0
			num_of_words_moved += self.move_to_end_of_word(amt, traverse_line_breaks, is_part_of_word)
		}
	}
	return
}

func (self *Readline) move_to_start_of_word(amt uint, traverse_line_breaks bool, is_part_of_word func(string) bool) (num_of_words_moved uint) {
	if amt == 0 {
		return 0
	}
	line := self.input_state.lines[self.input_state.cursor.Y]
	in_word := false
	ci := wcswidth.NewCellIterator(line[:self.input_state.cursor.X]).GotoEnd()
	sz := 0

	for ci.Backward() {
		current_is_word_char := is_part_of_word(ci.Current())
		plen := sz
		sz += len(ci.Current())
		if current_is_word_char {
			in_word = true
		} else if in_word {
			self.input_state.cursor.X -= plen
			amt--
			num_of_words_moved++
			if amt == 0 {
				return
			}
			in_word = false
		}
	}
	if self.move_to_start_of_line() {
		amt--
		num_of_words_moved++
	}
	if amt > 0 {
		if traverse_line_breaks && self.input_state.cursor.Y > 0 {
			self.input_state.cursor.Y--
			self.input_state.cursor.X = len(self.input_state.lines[self.input_state.cursor.Y])
			num_of_words_moved += self.move_to_start_of_word(amt, traverse_line_breaks, has_word_chars)
		}
	}
	return
}

func (self *Readline) kill_text(text string) {
	if ActionStartKillActions < self.last_action && self.last_action < ActionEndKillActions {
		self.kill_ring.append_to_existing_item(text)
	} else {
		self.kill_ring.add_new_item(text)
	}
}

func (self *Readline) kill_to_end_of_line() bool {
	line := self.input_state.lines[self.input_state.cursor.Y]
	if self.input_state.cursor.X >= len(line) {
		return false
	}
	self.input_state.lines[self.input_state.cursor.Y] = line[:self.input_state.cursor.X]
	self.kill_text(line[self.input_state.cursor.X:])
	return true
}

func (self *Readline) kill_to_start_of_line() bool {
	line := self.input_state.lines[self.input_state.cursor.Y]
	if self.input_state.cursor.X <= 0 {
		return false
	}
	self.input_state.lines[self.input_state.cursor.Y] = line[self.input_state.cursor.X:]
	self.kill_text(line[:self.input_state.cursor.X])
	self.input_state.cursor.X = 0
	return true
}

func (self *Readline) kill_next_word(amt uint, traverse_line_breaks bool) (num_killed uint) {
	before := self.input_state.cursor
	num_killed = self.move_to_end_of_word(amt, traverse_line_breaks, has_word_chars)
	if num_killed > 0 {
		self.kill_text(self.erase_between(before, self.input_state.cursor))
	}
	return num_killed
}

func (self *Readline) kill_previous_word(amt uint, traverse_line_breaks bool) (num_killed uint) {
	before := self.input_state.cursor
	num_killed = self.move_to_start_of_word(amt, traverse_line_breaks, has_word_chars)
	if num_killed > 0 {
		self.kill_text(self.erase_between(self.input_state.cursor, before))
	}
	return num_killed
}

func has_no_space_chars(text string) bool {
	for _, r := range text {
		if unicode.IsSpace(r) {
			return false
		}
	}
	return true
}

func (self *Readline) kill_previous_space_delimited_word(amt uint, traverse_line_breaks bool) (num_killed uint) {
	before := self.input_state.cursor
	num_killed = self.move_to_start_of_word(amt, traverse_line_breaks, has_no_space_chars)
	if num_killed > 0 {
		self.kill_text(self.erase_between(self.input_state.cursor, before))
	}
	return num_killed
}

func (self *Readline) ensure_position_in_bounds(pos *Position) *Position {
	pos.Y = max(0, min(pos.Y, len(self.input_state.lines)-1))
	line := self.input_state.lines[pos.Y]
	pos.X = max(0, min(pos.X, len(line)))
	return pos
}

func (self *Readline) yank(repeat_count uint, pop bool) bool {
	if pop && self.last_action != ActionYank && self.last_action != ActionPopYank {
		return false
	}
	text := ""
	if pop {
		text = self.kill_ring.pop_yank()
	} else {
		text = self.kill_ring.yank()
	}
	if text == "" {
		return false
	}
	before := self.input_state.cursor
	if pop {
		self.ensure_position_in_bounds(&self.last_yank_extent.start)
		self.ensure_position_in_bounds(&self.last_yank_extent.end)
		self.erase_between(self.last_yank_extent.start, self.last_yank_extent.end)
		self.input_state.cursor = self.last_yank_extent.start
		before = self.input_state.cursor
	}
	self.add_text(text)
	self.last_yank_extent.start = before
	self.last_yank_extent.end = self.input_state.cursor
	return true
}

func (self *Readline) history_first() bool {
	self.create_history_matches()
	return self.history_matches.first(self)
}

func (self *Readline) history_last() bool {
	self.create_history_matches()
	return self.history_matches.last(self)
}

func (self *Readline) history_prev(repeat_count uint) bool {
	self.create_history_matches()
	return self.history_matches.previous(repeat_count, self)
}

func (self *Readline) history_next(repeat_count uint) bool {
	self.create_history_matches()
	return self.history_matches.next(repeat_count, self)
}

func (self *Readline) _perform_action(ac Action, repeat_count uint) (err error, dont_set_last_action bool) {
	switch ac {
	case ActionBackspace:
		if self.history_search != nil {
			if self.remove_text_from_history_search(repeat_count) > 0 {
				return
			}
		} else {
			if self.erase_chars_before_cursor(repeat_count, true) > 0 {
				return
			}
		}
	case ActionDelete:
		if self.erase_chars_after_cursor(repeat_count, true) > 0 {
			return
		}
	case ActionMoveToStartOfLine:
		if self.move_to_start_of_line() {
			return
		}
	case ActionMoveToEndOfLine:
		if self.move_to_end_of_line() {
			return
		}
	case ActionMoveToEndOfWord:
		if self.move_to_end_of_word(repeat_count, true, has_word_chars) > 0 {
			return
		}
	case ActionMoveToStartOfWord:
		if self.move_to_start_of_word(repeat_count, true, has_word_chars) > 0 {
			return
		}
	case ActionMoveToStartOfDocument:
		if self.move_to_start() {
			return
		}
	case ActionMoveToEndOfDocument:
		if self.move_to_end() {
			return
		}
	case ActionCursorLeft:
		if self.move_cursor_left(repeat_count, true) > 0 {
			return
		}
	case ActionCursorRight:
		if self.move_cursor_right(repeat_count, true) > 0 {
			return
		}
	case ActionEndInput:
		line := self.input_state.lines[self.input_state.cursor.Y]
		if line == "" {
			err = io.EOF

		} else {
			err = self.perform_action(ActionAcceptInput, 1)
		}
		return
	case ActionAcceptInput:
		err = ErrAcceptInput
		return
	case ActionCursorUp:
		if self.move_cursor_vertically(-int(repeat_count)) != 0 {
			return
		}
	case ActionCursorDown:
		if self.move_cursor_vertically(int(repeat_count)) != 0 {
			return
		}
	case ActionHistoryPreviousOrCursorUp:
		dont_set_last_action = true
		if self.perform_action(ActionCursorUp, repeat_count) == ErrCouldNotPerformAction {
			err = self.perform_action(ActionHistoryPrevious, repeat_count)
		}
		return
	case ActionHistoryNextOrCursorDown:
		dont_set_last_action = true
		if self.perform_action(ActionCursorDown, repeat_count) == ErrCouldNotPerformAction {
			err = self.perform_action(ActionHistoryNext, repeat_count)
		}
		return
	case ActionHistoryFirst:
		if self.history_first() {
			return
		}
	case ActionHistoryPrevious:
		if self.history_prev(repeat_count) {
			return
		}
	case ActionHistoryNext:
		if self.history_next(repeat_count) {
			return
		}
	case ActionHistoryLast:
		if self.history_last() {
			return
		}
	case ActionClearScreen:
		self.loop.StartAtomicUpdate()
		self.loop.ClearScreen()
		self.RedrawNonAtomic()
		self.loop.EndAtomicUpdate()
		return
	case ActionKillToEndOfLine:
		if self.kill_to_end_of_line() {
			return
		}
	case ActionKillToStartOfLine:
		if self.kill_to_start_of_line() {
			return
		}
	case ActionKillNextWord:
		if self.kill_next_word(repeat_count, true) > 0 {
			return
		}
	case ActionKillPreviousWord:
		if self.kill_previous_word(repeat_count, true) > 0 {
			return
		}
	case ActionKillPreviousSpaceDelimitedWord:
		if self.kill_previous_space_delimited_word(repeat_count, true) > 0 {
			return
		}
	case ActionYank:
		if self.yank(repeat_count, false) {
			return
		}
	case ActionPopYank:
		if self.yank(repeat_count, true) {
			return
		}
	case ActionAbortCurrentLine:
		self.loop.QueueWriteString("\r\n")
		self.ResetText()
		return
	case ActionHistoryIncrementalSearchForwards:
		if self.history_search == nil {
			self.create_history_search(false, repeat_count)
			return
		}
		if self.next_history_search(false, repeat_count) {
			return
		}
	case ActionHistoryIncrementalSearchBackwards:
		if self.history_search == nil {
			self.create_history_search(true, repeat_count)
			return
		}
		if self.next_history_search(true, repeat_count) {
			return
		}
	case ActionAddText:
		text := strings.Repeat(self.text_to_be_added, int(repeat_count))
		self.text_to_be_added = ""
		if self.history_search != nil {
			self.add_text_to_history_search(text)
		} else {
			self.add_text(text)
		}
		return
	case ActionTerminateHistorySearchAndRestore:
		if self.history_search != nil {
			self.end_history_search(false)
			return
		}
	case ActionTerminateHistorySearchAndApply:
		if self.history_search != nil {
			self.end_history_search(true)
			return
		}
	case ActionCompleteForward:
		if self.complete(true, repeat_count) {
			return
		}
	case ActionCompleteBackward:
		if self.complete(false, repeat_count) {
			return
		}
	}
	err = ErrCouldNotPerformAction
	return
}

func (self *Readline) perform_action(ac Action, repeat_count uint) error {
	err, dont_set_last_action := self._perform_action(ac, repeat_count)
	if err == nil && !dont_set_last_action {
		self.last_action = ac
		if self.completions.current.results != nil && ac != ActionCompleteForward && ac != ActionCompleteBackward {
			self.completions.current = completion{}
		}
	}
	return err
}
