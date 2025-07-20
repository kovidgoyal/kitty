// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package wcswidth

import (
	"errors"
	"fmt"
	"io"
	"strconv"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type truncate_error struct {
	pos, width int
}

func (self *truncate_error) Error() string {
	return fmt.Sprint("Truncation at:", self.pos, " with width:", self.width)
}

type truncate_iterator struct {
	w WCWidthIterator

	pos, limit        int
	limit_exceeded_at *truncate_error
}

func (self *truncate_iterator) handle_csi(csi []byte) error {
	if len(csi) > 1 && csi[len(csi)-1] == 'b' { // repeat previous char escape code
		num_string := utils.UnsafeBytesToString(csi[:len(csi)-1])
		n, err := strconv.Atoi(num_string)
		if err == nil && n > 0 {
			width_before_repeat := self.w.current_width
			for ; n > 0; n-- {
				self.w.handle_rune(self.w.prev_ch)
				if self.w.current_width > self.limit {
					return &truncate_error{pos: self.pos, width: width_before_repeat}
				}
			}
		}
	}
	self.pos += len(csi) + 2
	return nil
}

func (self *truncate_iterator) handle_st_terminated_escape_code(body []byte) error {
	self.pos += len(body) + 4
	return nil
}

func KeepOnlyCSI(text string, output io.Writer) {
	var w WCWidthIterator
	w.parser.HandleCSI = func(data []byte) (err error) {
		_, err = output.Write([]byte{'\x1b', '['})
		if err == nil {
			_, err = output.Write(data)
		}
		return
	}
}

func create_truncate_iterator() *truncate_iterator {
	var ans truncate_iterator
	ans.w.parser.HandleRune = ans.handle_rune
	ans.w.parser.HandleCSI = ans.handle_csi
	ans.w.parser.HandleOSC = ans.handle_st_terminated_escape_code
	ans.w.parser.HandleAPC = ans.handle_st_terminated_escape_code
	ans.w.parser.HandleDCS = ans.handle_st_terminated_escape_code
	ans.w.parser.HandlePM = ans.handle_st_terminated_escape_code
	ans.w.parser.HandleSOS = ans.handle_st_terminated_escape_code
	return &ans
}

func (self *truncate_iterator) handle_rune(ch rune) error {
	width := self.w.current_width
	self.w.handle_rune(ch)
	if self.limit_exceeded_at != nil {
		if self.w.current_width <= self.limit { // emoji variation selectors can cause width to decrease
			return &truncate_error{pos: self.pos + len(string(ch)), width: self.w.current_width}
		}
		return self.limit_exceeded_at
	}
	if self.w.current_width > self.limit {
		self.limit_exceeded_at = &truncate_error{pos: self.pos, width: width}
	}
	self.pos += len(string(ch))
	return nil
}

func (self *truncate_iterator) parse(b []byte) (ans int, width int) {
	err := self.w.parser.Parse(b)
	var te *truncate_error
	if err != nil && errors.As(err, &te) {
		return te.pos, te.width
	}
	if self.limit_exceeded_at != nil {
		return self.limit_exceeded_at.pos, self.limit_exceeded_at.width
	}
	return len(b), self.w.current_width
}

func TruncateToVisualLengthWithWidth(text string, length int) (truncated string, width_of_truncated int) {
	if length < 1 {
		return text[:0], 0
	}
	t := create_truncate_iterator()
	t.limit = length
	t.limit_exceeded_at = nil
	t.w.current_width = 0
	truncate_point, width := t.parse(utils.UnsafeStringToBytes(text))
	return text[:truncate_point], width
}

func TruncateToVisualLength(text string, length int) string {
	ans, _ := TruncateToVisualLengthWithWidth(text, length)
	return ans
}
