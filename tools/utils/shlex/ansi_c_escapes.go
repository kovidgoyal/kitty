// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shlex

import (
	"fmt"
	"strconv"
	"strings"
	"unicode/utf8"
)

var _ = fmt.Print

type state int

const (
	normal state = iota
	control_char
	backslash
	hex_digit
	oct_digit
)

type ansi_c struct {
	state                        state
	max_num_of_digits, digit_idx int
	digits                       [16]rune
	output                       strings.Builder
}

func is_hex_char(ch rune) bool {
	return ('0' <= ch && ch <= '9') || ('a' <= ch && ch <= 'f') || ('A' <= ch && ch <= 'F')
}

func is_oct_char(ch rune) bool {
	return '0' <= ch && ch <= '7'
}

func (self *ansi_c) write_digits(base int) {
	if self.digit_idx > 0 {
		text := string(self.digits[:self.digit_idx])
		if val, err := strconv.ParseUint(text, base, 32); err == nil && val <= utf8.MaxRune {
			self.output.WriteRune(rune(val))
		}
	}
	self.digit_idx = 0
	self.state = normal
}

func (self *ansi_c) parse(ch rune) {
	switch self.state {
	case normal:
		if ch == '\\' {
			self.state = backslash
		} else {
			self.output.WriteRune(ch)
		}
	case control_char:
		self.output.WriteRune(ch & 0x1f)
		self.state = normal
	case hex_digit:
		if self.digit_idx < self.max_num_of_digits && is_hex_char(ch) {
			self.digits[self.digit_idx] = ch
			self.digit_idx++
		} else {
			self.write_digits(16)
			self.parse(ch)
		}
	case oct_digit:
		if self.digit_idx < self.max_num_of_digits && is_oct_char(ch) {
			self.digits[self.digit_idx] = ch
			self.digit_idx++
		} else {
			self.write_digits(8)
			self.parse(ch)
		}
	case backslash:
		self.state = normal
		switch ch {
		default:
			self.output.WriteRune('\\')
			self.output.WriteRune(ch)
		case 'a':
			self.output.WriteRune(7)
		case 'b':
			self.output.WriteRune(8)
		case 'c':
			self.state = control_char
		case 'e', 'E':
			self.output.WriteRune(27)
		case 'f':
			self.output.WriteRune(12)
		case 'n':
			self.output.WriteRune(10)
		case 'r':
			self.output.WriteRune(13)
		case 't':
			self.output.WriteRune(9)
		case 'v':
			self.output.WriteRune(11)
		case 'x':
			self.max_num_of_digits, self.digit_idx, self.state = 2, 0, hex_digit
		case 'u':
			self.max_num_of_digits, self.digit_idx, self.state = 4, 0, hex_digit
		case 'U':
			self.max_num_of_digits, self.digit_idx, self.state = 8, 0, hex_digit
		case '0', '1', '2', '3', '4', '5', '6', '7':
			self.max_num_of_digits, self.digit_idx, self.state = 3, 1, oct_digit
			self.digits[0] = ch
		case '\\':
			self.output.WriteRune('\\')
		case '?':
			self.output.WriteRune('?')
		case '"':
			self.output.WriteRune('"')
		case '\'':
			self.output.WriteRune('\'')

		}
	}
}

func (self *ansi_c) finish() string {
	switch self.state {
	case hex_digit:
		self.write_digits(16)
	case oct_digit:
		self.write_digits(8)
	case backslash:
		self.output.WriteRune('\\')
	case control_char:
		self.output.WriteString("\\c")
	}
	self.state = normal
	self.digit_idx = 0
	s := self.output.String()
	self.output.Reset()
	return s
}

func ExpandANSICEscapes(src string) string {
	p := ansi_c{}
	p.output.Grow(len(src))
	for _, ch := range src {
		p.parse(ch)
	}
	return p.finish()
}
