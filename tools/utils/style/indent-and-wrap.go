// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"fmt"
	"strconv"
	"strings"
	"unicode"

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
	ans := make([]string, 0, 4)
	if for_close {
		if self.bold || self.dim {
			ans = append(ans, "22")
		}
		if self.italic {
			ans = append(ans, "23")
		}
		if self.reverse {
			ans = append(ans, "27")
		}
		if self.strikethrough {
			ans = append(ans, "29")
		}
		if self.underline_style != no_underline && self.underline_style != nil_underline {
			ans = append(ans, "4:0")
		}
		if self.fg.number != 0 {
			ans = append(ans, "39")
		}
		if self.bg.number != 0 {
			ans = append(ans, "49")
		}
		if self.uc.number != 0 {
			ans = append(ans, "59")
		}
	} else {
		if self.bold {
			ans = append(ans, "1")
		}
		if self.dim {
			ans = append(ans, "2")
		}
		if self.italic {
			ans = append(ans, "3")
		}
		if self.reverse {
			ans = append(ans, "7")
		}
		if self.strikethrough {
			ans = append(ans, "9")
		}
		if self.underline_style != no_underline && self.underline_style != nil_underline {
			ans = append(ans, fmt.Sprintf("4:%d", self.underline_style))
		}
		if q := self.fg.as_sgr(30); q != "" {
			ans = append(ans, q)
		}
		if q := self.bg.as_sgr(40); q != "" {
			ans = append(ans, q)
		}
		if q := self.uc.as_sgr(50); q != "" {
			ans = append(ans, q)
		}
	}
	return strings.Join(ans, ";")
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
		case 2:
			self.dim, self.bold = true, false
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

func (self hyperlink_state) reset() {
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
	buf                       strings.Builder
	last_text_pos, cursor_pos int
}

func (self *line_builder) reset() string {
	ans := self.buf.String()
	if len(ans) > self.last_text_pos {
		ans = ans[:self.last_text_pos]
	}
	sz := self.buf.Len()
	self.buf.Reset()
	self.last_text_pos = 0
	self.cursor_pos = 0
	if sz > 1024 {
		self.buf.Grow(sz)
	} else {
		self.buf.Grow(1024)
	}
	return ans
}

func (self *line_builder) has_space_for_width(w, max_width int) bool {
	return w+self.cursor_pos <= max_width
}

func (self *line_builder) add_char(ch rune) {
	self.buf.WriteRune(ch)
	self.last_text_pos = self.buf.Len()
	self.cursor_pos += wcswidth.Runewidth(ch)
}

func (self *line_builder) add_word(word string, width int) {
	self.buf.WriteString(word)
	self.last_text_pos = self.buf.Len()
	self.cursor_pos += width
}

func (self *line_builder) add_escape_code(code string) {
	self.buf.WriteString(code)
}

func (self *line_builder) add_escape_code2(prefix string, body []byte, suffix string) {
	self.buf.WriteString(prefix)
	self.buf.Write(body)
	self.buf.WriteString(suffix)
}

type wrapper struct {
	ep                  wcswidth.EscapeCodeParser
	indent              string
	width, indent_width int

	sgr          sgr_state
	hyperlink    hyperlink_state
	current_word strings.Builder
	current_line line_builder
	lines        []string
}

func (self *wrapper) newline_prefix() {
	self.current_line.add_escape_code(self.sgr.as_escape_codes(true))
	self.current_line.add_escape_code(self.hyperlink.as_escape_codes(true))
	self.current_line.add_word(self.indent, self.indent_width)
	self.current_line.add_escape_code(self.sgr.as_escape_codes(false))
	self.current_line.add_escape_code(self.hyperlink.as_escape_codes(false))
}

func (self *wrapper) end_current_line() {
	line := self.current_line.reset()
	line = strings.TrimRightFunc(line, unicode.IsSpace)
	if strings.HasSuffix(line, self.indent) && wcswidth.Stringwidth(line) == self.indent_width {
		line = line[:len(line)-len(self.indent)]
	}
	self.lines = append(self.lines, line)
	self.newline_prefix()
}

func (self *wrapper) print_word() {
	w := wcswidth.Stringwidth(self.current_word.String())
	if !self.current_line.has_space_for_width(w, self.width) {
		self.end_current_line()
		s := strings.TrimSpace(self.current_word.String())
		self.current_word.Reset()
		self.current_word.WriteString(s)
		w = wcswidth.Stringwidth(s)
	}
	self.current_line.add_word(self.current_word.String(), w)
	self.current_word.Reset()
}

func (self *wrapper) handle_rune(ch rune) error {
	if ch == '\n' {
		self.print_word()
		self.end_current_line()
	} else if self.current_word.Len() != 0 && ch != 0xa0 && unicode.IsSpace(ch) {
		self.print_word()
		self.current_line.add_char(ch)
	} else {
		self.current_word.WriteRune(ch)
	}
	return nil
}

func (self *wrapper) handle_csi(raw []byte) error {
	self.sgr.apply_csi(utils.UnsafeBytesToString(raw))
	self.current_line.add_escape_code2("\x1b[", raw, "")
	return nil
}

func (self *wrapper) handle_osc(raw []byte) error {
	self.hyperlink.apply_osc(utils.UnsafeBytesToString(raw))
	self.current_line.add_escape_code2("\x1b]", raw, "\x1b\\")
	return nil
}

func (self *wrapper) wrap_text(text string) string {
	if text == "" {
		return text
	}
	self.current_line.reset()
	self.current_word.Reset()
	self.lines = self.lines[:0]
	self.current_line.add_word(self.indent, self.indent_width)
	self.ep.ParseString(text)
	if self.current_word.Len() > 0 {
		self.print_word()
	}
	self.end_current_line()
	last_line := self.current_line.reset()
	self.newline_prefix()
	if last_line == self.current_line.reset() {
		last_line = ""
	}
	self.lines = append(self.lines, last_line)
	return strings.Join(self.lines, "\n")
}

func new_wrapper(indent string, width int) *wrapper {
	ans := wrapper{indent: indent, width: width, indent_width: wcswidth.Stringwidth(indent)}
	ans.ep.HandleRune = ans.handle_rune
	ans.ep.HandleCSI = ans.handle_csi
	ans.ep.HandleOSC = ans.handle_osc
	ans.lines = make([]string, 0, 32)
	return &ans
}

func WrapText(text string, indent string, width int) string {
	w := new_wrapper(indent, width)
	return w.wrap_text(text)
}
