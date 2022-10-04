// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"
	"strings"

	"kitty/tools/utils"
)

var _ = fmt.Print

func (self *Readline) add_text(text string) {
	new_lines := make([]string, 0, len(self.lines)+4)
	new_lines = append(new_lines, self.lines[:self.cursor_line]...)
	var lines_after []string
	if len(self.lines) > self.cursor_line+1 {
		lines_after = self.lines[self.cursor_line+1:]
	}
	has_trailing_newline := strings.HasSuffix(text, "\n")

	add_line_break := func() {
		new_lines = append(new_lines, "")
		self.cursor_pos_in_line = 0
		self.cursor_line += 1
	}
	cline := self.lines[self.cursor_line]
	before_first_line := cline[:self.cursor_pos_in_line]
	after_first_line := ""
	if self.cursor_pos_in_line < len(cline) {
		after_first_line = cline[self.cursor_pos_in_line:]
	}
	for i, line := range utils.Splitlines(text) {
		if i > 0 {
			add_line_break()
			new_lines = append(new_lines, line)
			self.cursor_pos_in_line = len(line)
		} else {
			line := before_first_line + line
			self.cursor_pos_in_line = len(line)
			line += after_first_line
		}
	}
	if has_trailing_newline {
		add_line_break()
	}
	if len(lines_after) > 0 {
		new_lines = append(new_lines, lines_after...)
	}
	self.lines = new_lines
}
