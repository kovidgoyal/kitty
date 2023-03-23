// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"fmt"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	"kitty/tools/utils"
	"kitty/tools/wcswidth"
)

type sgr_color struct {
	number int
	color  RGBA
}

func (self sgr_color) as_sgr(base int) string {
	if self.number == 0 {
		return ""
	}
	if self.number > 0 {
		n := self.number - 1
		if n <= 15 && (base == 30 || base == 40) {
			if n <= 7 {
				return strconv.Itoa(base + n)
			}
			return strconv.Itoa(base + 60 + n - 7)
		}
		return fmt.Sprintf("%d:5:%d", base+8, n)
	}
	return fmt.Sprintf("%d:2:%d:%d:%d", base+8, self.color.Red, self.color.Green, self.color.Blue)
}

func (self *sgr_color) from_extended(nums []int) bool {
	switch nums[0] {
	case 5:
		if len(nums) > 1 {
			self.number = 1 + nums[1]
			return true
		}
	case 2:
		if len(nums) > 3 {
			self.number = -1
			self.color.Red = uint8(nums[1])
			self.color.Green = uint8(nums[2])
			self.color.Blue = uint8(nums[3])
			return true
		}
	}
	return false
}

type sgr_state struct {
	italic, reverse, bold, dim, strikethrough bool
	underline_style                           underline_style
	fg, bg, uc                                sgr_color
}

func (self *sgr_state) reset() {
	*self = sgr_state{}
}

func (self sgr_state) as_sgr(for_close bool) string {
	ans := make([]byte, 0, 32)
	if for_close {
		if self.bold {
			ans = append(ans, "221;"...)
		}
		if self.dim {
			ans = append(ans, "222;"...)
		}
		if self.italic {
			ans = append(ans, "23;"...)
		}
		if self.reverse {
			ans = append(ans, "27;"...)
		}
		if self.strikethrough {
			ans = append(ans, "29;"...)
		}
		if self.underline_style != no_underline && self.underline_style != nil_underline {
			ans = append(ans, "4:0;"...)
		}
		if self.fg.number != 0 {
			ans = append(ans, "39;"...)
		}
		if self.bg.number != 0 {
			ans = append(ans, "49;"...)
		}
		if self.uc.number != 0 {
			ans = append(ans, "59;"...)
		}
	} else {
		if self.bold {
			ans = append(ans, "1;"...)
		}
		if self.dim {
			ans = append(ans, "2;"...)
		}
		if self.italic {
			ans = append(ans, "3;"...)
		}
		if self.reverse {
			ans = append(ans, "7;"...)
		}
		if self.strikethrough {
			ans = append(ans, "9;"...)
		}
		if self.underline_style != no_underline && self.underline_style != nil_underline {
			ans = append(ans, fmt.Sprintf("4:%d;", self.underline_style)...)
		}
		if q := self.fg.as_sgr(30); q != "" {
			ans = append(ans, q...)
			ans = append(ans, ';')
		}
		if q := self.bg.as_sgr(40); q != "" {
			ans = append(ans, q...)
			ans = append(ans, ';')
		}
		if q := self.uc.as_sgr(50); q != "" {
			ans = append(ans, q...)
			ans = append(ans, ';')
		}
	}
	if len(ans) > 0 {
		ans = ans[:len(ans)-1]
	}
	return utils.UnsafeBytesToString(ans)
}

func (self sgr_state) as_escape_codes(for_close bool) string {
	q := self.as_sgr(for_close)
	if q == "" {
		return q
	}
	return fmt.Sprintf("\x1b[%sm", q)
}

func (self *sgr_state) apply_csi(raw string) {
	if !strings.HasSuffix(raw, "m") {
		return
	}
	raw = raw[:len(raw)-1]
	if raw == "" {
		raw = "0"
	}
	parts := strings.Split(raw, ";")
	nums := make([]int, 0, 8)
	for _, part := range parts {
		subparts := strings.Split(part, ":")
		nums = nums[:0]
		for _, b := range subparts {
			q, err := strconv.Atoi(b)
			if err == nil {
				nums = append(nums, q)
			}
		}
		if len(nums) == 0 {
			continue
		}
		switch nums[0] {
		case 0:
			self.reset()
		case 1:
			self.dim, self.bold = false, true
		case 221:
			self.bold = false
		case 2:
			self.dim, self.bold = true, false
		case 222:
			self.dim = false
		case 22:
			self.dim, self.bold = false, false
		case 3:
			self.italic = true
		case 23:
			self.italic = false
		case 7:
			self.reverse = true
		case 27:
			self.reverse = false
		case 9:
			self.strikethrough = true
		case 29:
			self.strikethrough = false
		case 24:
			self.underline_style = no_underline
		case 4:
			us := 1
			if len(nums) > 1 {
				us = nums[1]
			}
			switch us {
			case 0:
				self.underline_style = no_underline
			case 1:
				self.underline_style = straight_underline
			case 2:
				self.underline_style = double_underline
			case 3:
				self.underline_style = curly_underline
			case 4:
				self.underline_style = dotted_underline
			case 5:
				self.underline_style = dashed_underline
			}
		case 30, 31, 32, 33, 34, 35, 36, 37:
			self.fg.number = nums[0] + 1 - 30
		case 90, 91, 92, 93, 94, 95, 96, 97:
			self.fg.number = nums[0] + 1 - 82
		case 38:
			self.fg.from_extended(nums[1:])
		case 39:
			self.fg.number = 0
		case 40, 41, 42, 43, 44, 45, 46, 47:
			self.bg.number = nums[0] + 1 - 40
		case 100, 101, 102, 103, 104, 105, 106, 107:
			self.bg.number = nums[0] + 1 - 92
		case 48:
			self.bg.from_extended(nums[1:])
		case 49:
			self.bg.number = 0
		case 58:
			self.uc.from_extended(nums[1:])
		case 59:
			self.uc.number = 0
		}
	}
}

type hyperlink_state struct {
	id, url string
}

func (self *hyperlink_state) apply_osc(raw string) {
	parts := strings.SplitN(raw, ";", 3)
	if len(parts) != 3 || parts[0] != "8" {
		return
	}
	self.id = parts[1]
	self.url = parts[2]
}

func (self *hyperlink_state) reset() {
	self.id = ""
	self.url = ""
}

func (self hyperlink_state) as_escape_codes(for_close bool) string {
	if self.id == "" && self.url == "" {
		return ""
	}
	if for_close {
		return "\x1b]8;;\x1b\\"
	}
	return fmt.Sprintf("\x1b]8;%s;%s\x1b\\", self.id, self.url)
}

type line_builder struct {
	buf                       []byte
	last_text_pos, cursor_pos int
}

func (self *line_builder) reset() string {
	ans := string(self.buf)
	if len(ans) > self.last_text_pos {
		prefix := ans[:self.last_text_pos]
		suffix := ans[self.last_text_pos:]
		prefix = strings.TrimRightFunc(prefix, unicode.IsSpace)
		if len(prefix) != self.last_text_pos {
			ans = prefix + suffix
		}
	} else {
		ans = strings.TrimRightFunc(ans, unicode.IsSpace)
	}
	self.buf = self.buf[:0]
	self.last_text_pos = 0
	self.cursor_pos = 0
	return ans
}

func (self *line_builder) has_space_for_width(w, max_width int) bool {
	return w+self.cursor_pos <= max_width
}

func (self *line_builder) add_char(ch rune) {
	self.buf = utf8.AppendRune(self.buf, ch)
	self.last_text_pos = len(self.buf)
	self.cursor_pos += wcswidth.Runewidth(ch)
}

func (self *line_builder) add_word(word []byte, width int) {
	self.buf = append(self.buf, word...)
	self.last_text_pos = len(self.buf)
	self.cursor_pos += width
}

func (self *line_builder) add_escape_code(code string) {
	self.buf = append(self.buf, code...)
}

func (self *line_builder) add_escape_code2(prefix string, body []byte, suffix string) {
	self.buf = append(self.buf, prefix...)
	self.buf = append(self.buf, body...)
	self.buf = append(self.buf, suffix...)
}

type escape_code_ struct {
	prefix, body, suffix string
}

type word_builder struct {
	buf                 []byte
	escape_codes        []escape_code_
	text_start_position int
	wcswidth            *wcswidth.WCWidthIterator
}

func (self *word_builder) reset(copy_current_word func([]byte)) {
	copy_current_word(self.buf)
	self.buf = self.buf[:0]
	self.escape_codes = self.escape_codes[:0]
	self.text_start_position = 0
	self.wcswidth.Reset()
}

func (self *word_builder) is_empty() bool {
	return len(self.buf) == 0
}

func (self *word_builder) width() int {
	return self.wcswidth.CurrentWidth()
}

func (self *word_builder) add_escape_code(prefix string, body []byte, suffix string) {
	e := escape_code_{prefix: prefix, body: string(body), suffix: suffix}
	self.escape_codes = append(self.escape_codes, e)
	self.buf = append(self.buf, prefix...)
	self.buf = append(self.buf, body...)
	self.buf = append(self.buf, suffix...)
}

func (self *word_builder) has_text() bool { return self.text_start_position != 0 }

func (self *word_builder) recalculate_width() {
	self.wcswidth.Reset()
	self.wcswidth.Parse(self.buf)
}

func (self *word_builder) trim_leading_spaces() {
	if self.is_empty() {
		return
	}
	s := utils.UnsafeBytesToString(self.buf)
	var before, after string
	if self.text_start_position != 0 {
		before, after = s[:self.text_start_position-1], s[self.text_start_position-1:]
	} else {
		after = s
	}
	q := strings.TrimLeftFunc(after, unicode.IsSpace)
	if q != after {
		self.buf = make([]byte, 0, len(s))
		self.buf = append(self.buf, before...)
		self.buf = append(self.buf, q...)
		self.text_start_position = len(before) + 1
		self.recalculate_width()
	}
}

func (self *word_builder) add_rune(ch rune) (num_bytes_written int) {
	before := len(self.buf)
	self.buf = utf8.AppendRune(self.buf, ch)
	num_bytes_written = len(self.buf) - before
	for _, b := range self.buf[before:] {
		self.wcswidth.ParseByte(b)
	}
	if self.text_start_position == 0 {
		self.text_start_position = len(self.buf)
	}
	return
}

func (self *word_builder) remove_trailing_bytes(n int) {
	self.buf = self.buf[:len(self.buf)-n]
	self.recalculate_width()
}

type wrapper struct {
	ep                  wcswidth.EscapeCodeParser
	indent              string
	width, indent_width int

	sgr                     sgr_state
	hyperlink               hyperlink_state
	current_word            word_builder
	current_line            line_builder
	lines                   []string
	ignore_lines_containing []string
}

func (self *wrapper) newline_prefix() {
	self.current_line.add_escape_code(self.sgr.as_escape_codes(true))
	self.current_line.add_escape_code(self.hyperlink.as_escape_codes(true))
	self.current_line.add_word(utils.UnsafeStringToBytes(self.indent), self.indent_width)
	self.current_line.add_escape_code(self.sgr.as_escape_codes(false))
	self.current_line.add_escape_code(self.hyperlink.as_escape_codes(false))
}

func (self *wrapper) append_line(line string) {
	for _, q := range self.ignore_lines_containing {
		if strings.Contains(line, q) {
			return
		}
	}
	self.lines = append(self.lines, line)
}

func (self *wrapper) end_current_line() {
	line := self.current_line.reset()
	if strings.HasSuffix(line, self.indent) && wcswidth.Stringwidth(line) == self.indent_width {
		line = line[:len(line)-len(self.indent)]
	}
	self.append_line(line)
	self.newline_prefix()
}

func (self *wrapper) print_word() {
	w := self.current_word.width()
	if !self.current_line.has_space_for_width(w, self.width) {
		self.end_current_line()
		self.current_word.trim_leading_spaces()
		w = self.current_word.width()
	}
	for _, e := range self.current_word.escape_codes {
		if e.suffix != "" {
			self.hyperlink.apply_osc(e.body)
		} else {
			self.sgr.apply_csi(e.body)
		}
	}
	self.current_word.reset(func(word []byte) {
		self.current_line.add_word(word, w)
	})
}

func (self *wrapper) handle_rune(ch rune) error {
	if ch == '\n' {
		self.print_word()
		self.end_current_line()
	} else if self.current_word.has_text() && ch != 0xa0 && unicode.IsSpace(ch) {
		self.print_word()
		self.current_line.add_char(ch)
	} else {
		num_of_bytes_written := self.current_word.add_rune(ch)
		if self.current_word.width() > self.width {
			self.current_word.remove_trailing_bytes(num_of_bytes_written)
			self.print_word()
			return self.handle_rune(ch)
		}
	}
	return nil
}

func (self *wrapper) handle_csi(raw []byte) error {
	self.current_word.add_escape_code("\x1b[", raw, "")
	return nil
}

func (self *wrapper) handle_osc(raw []byte) error {
	self.current_word.add_escape_code("\x1b]", raw, "\x1b\\")
	return nil
}

func (self *wrapper) wrap_text(text string) []string {
	if text == "" {
		return []string{""}
	}
	self.current_line.reset()
	self.current_word.reset(func([]byte) {})
	self.lines = self.lines[:0]
	self.current_line.add_word(utils.UnsafeStringToBytes(self.indent), self.indent_width)
	self.ep.ParseString(text)
	if !self.current_word.is_empty() {
		self.print_word()
	}
	self.end_current_line()
	last_line := self.current_line.reset()
	self.newline_prefix()
	if last_line == self.current_line.reset() {
		last_line = ""
	}
	if last_line != "" {
		self.append_line(last_line)
	}
	return self.lines
}

func new_wrapper(indent string, width int) *wrapper {
	width = utils.Max(2, width)
	ans := wrapper{indent: indent, width: width, indent_width: wcswidth.Stringwidth(indent)}
	ans.ep.HandleRune = ans.handle_rune
	ans.ep.HandleCSI = ans.handle_csi
	ans.ep.HandleOSC = ans.handle_osc
	ans.lines = make([]string, 0, 32)
	ans.current_word.escape_codes = make([]escape_code_, 0, 8)
	ans.current_word.wcswidth = wcswidth.CreateWCWidthIterator()
	return &ans
}

func WrapTextAsLines(text string, indent string, width int, ignore_lines_containing ...string) []string {
	w := new_wrapper(indent, width)
	w.ignore_lines_containing = ignore_lines_containing
	return w.wrap_text(text)
}

func WrapText(text string, indent string, width int, ignore_lines_containing ...string) string {
	return strings.Join(WrapTextAsLines(text, indent, width, ignore_lines_containing...), "\n")
}
