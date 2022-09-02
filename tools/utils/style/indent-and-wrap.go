// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"fmt"
	"io"
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

func (self sgr_state) as_sgr() string {
	ans := make([]string, 0, 4)
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
	return strings.Join(ans, ";")
}

func (self sgr_state) as_escape_codes() string {
	q := self.as_sgr()
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
		nums = nums[:len(subparts)]
		for i, b := range subparts {
			q, err := strconv.Atoi(b)
			if err != nil {
				nums[i] = q
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

func (self hyperlink_state) as_escape_codes() string {
	if self.id == "" && self.url == "" {
		return ""
	}
	return fmt.Sprintf("\x1b]8;%s;%s\x1b\\", self.id, self.url)
}

type wrapper struct {
	ep                  wcswidth.EscapeCodeParser
	output              io.Writer
	indent              string
	width, indent_width int

	sgr          sgr_state
	hyperlink    hyperlink_state
	current_word strings.Builder
	x            int
}

func (self *wrapper) print_newline() {
	fmt.Fprint(self.output, "\x1b[m\x1b]8;;\x1b\\\n", self.indent, self.sgr.as_escape_codes(), self.hyperlink.as_escape_codes())
	self.x = self.indent_width
}

func (self *wrapper) print_word(ch rune) {
	w := wcswidth.Stringwidth(self.current_word.String())
	if self.x+w > self.width {
		self.print_newline()
		s := strings.TrimSpace(self.current_word.String())
		self.current_word.Reset()
		self.current_word.WriteString(s)
	}
	fmt.Fprint(self.output, self.current_word.String())
	self.current_word.Reset()
	if ch > 0 {
		self.current_word.WriteRune(ch)
	}
	self.x += w
}

func (self *wrapper) handle_rune(ch rune) error {
	if ch == '\n' {
		self.print_newline()
	} else if self.current_word.Len() != 0 && ch != 0xa0 && unicode.IsSpace(ch) {
		self.print_word(ch)
	} else {
		self.current_word.WriteRune(ch)
	}

	io.WriteString(self.output, string(ch))
	return nil
}

func (self *wrapper) handle_csi(raw []byte) error {
	self.sgr.apply_csi(utils.UnsafeBytesToString(raw))
	self.output.Write(raw)
	return nil
}

func (self *wrapper) handle_osc(raw []byte) error {
	self.hyperlink.apply_osc(utils.UnsafeBytesToString(raw))
	self.output.Write(raw)
	return nil
}

func (self *wrapper) wrap_text(text string) {
	self.x = self.indent_width
	fmt.Fprint(self.output, self.indent)
	self.ep.ParseString(text)
	if self.current_word.Len() > 0 {
		self.print_word(0)
	}
	if len(text) > 0 {
		self.print_newline()
	}
}

func new_wrapper(output io.Writer, indent string, width int) *wrapper {
	ans := wrapper{output: output, indent: indent, width: width, indent_width: wcswidth.Stringwidth(indent)}
	ans.ep.HandleRune = ans.handle_rune
	ans.ep.HandleCSI = ans.handle_csi
	ans.ep.HandleOSC = ans.handle_osc
	return &ans
}

func WrapText(text string, output io.Writer, indent string, width int) {
	w := new_wrapper(output, indent, width)
	w.wrap_text(text)
	return
}
