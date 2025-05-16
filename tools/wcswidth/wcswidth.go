// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package wcswidth

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type WCWidthIterator struct {
	prev_ch                   rune
	prev_width, current_width int
	seg                       GraphemeSegmentationResult
	can_combine               bool
	parser                    EscapeCodeParser
	rune_count                uint
}

func CreateWCWidthIterator() *WCWidthIterator {
	var ans WCWidthIterator
	ans.parser.HandleRune = ans.handle_rune
	ans.parser.HandleCSI = ans.handle_csi
	ans.parser.HandleOSC = ans.handle_st_terminated
	ans.parser.HandleDCS = ans.handle_st_terminated
	ans.parser.HandlePM = ans.handle_st_terminated
	ans.parser.HandleSOS = ans.handle_st_terminated
	ans.parser.HandleAPC = ans.handle_st_terminated

	return &ans
}

func (self *WCWidthIterator) Reset() {
	self.prev_ch = 0
	self.prev_width = 0
	self.current_width = 0
	self.rune_count = 0
	self.can_combine = false
	self.seg = 0
	self.parser.Reset()
}

func (self *WCWidthIterator) handle_csi(csi []byte) error {
	if len(csi) > 1 && csi[len(csi)-1] == 'b' {
		num_string := utils.UnsafeBytesToString(csi[:len(csi)-1])
		n, err := strconv.Atoi(num_string)
		if err == nil && n > 0 {
			for i := 0; i < n; i++ {
				err = self.handle_rune(self.prev_ch)
				if err != nil {
					return err
				}
			}
		}
	}
	self.can_combine = false
	self.seg = 0
	return nil
}

func (self *WCWidthIterator) handle_st_terminated(data []byte) error {
	self.can_combine = false
	self.seg = 0
	return nil
}

func (self *WCWidthIterator) handle_rune(ch rune) error {
	self.rune_count += 1
	cp := CharPropsFor(ch)
	self.seg = self.seg.Step(cp)
	if self.can_combine && self.seg.Add_to_current_cell() == 1 {
		switch ch {
		case 0xfe0f:
			if CharPropsFor(self.prev_ch).Is_emoji_presentation_base() == 1 && self.prev_width == 1 {
				self.current_width += 1
				self.prev_width = 2
			}
		case 0xfe0e:
			if CharPropsFor(self.prev_ch).Is_emoji_presentation_base() == 1 && self.prev_width == 2 {
				self.current_width -= 1
				self.prev_width = 1
			}
		}
	} else {
		width := cp.Width()
		switch width {
		case -1:
		case 0:
			self.prev_width = 0
		case 2:
			self.prev_width = 2
		default:
			self.prev_width = 1
		}
		self.current_width += self.prev_width
		self.can_combine = true
	}
	self.prev_ch = ch
	return nil
}

func (self *WCWidthIterator) ParseByte(b byte) (ans int) {
	self.parser.ParseByte(b)
	return self.current_width
}

func (self *WCWidthIterator) Parse(b []byte) (ans int) {
	self.current_width = 0
	self.parser.Parse(b)
	return self.current_width
}

func (self *WCWidthIterator) CurrentWidth() int {
	return self.current_width
}

func Stringwidth(text string) int {
	w := CreateWCWidthIterator()
	return w.Parse(utils.UnsafeStringToBytes(text))
}

func StripEscapeCodes(text string) string {
	out := strings.Builder{}
	out.Grow(len(text))

	p := EscapeCodeParser{}
	p.HandleRune = func(ch rune) error {
		out.WriteRune(ch)
		return nil
	}
	p.ParseString(text)
	return out.String()
}
