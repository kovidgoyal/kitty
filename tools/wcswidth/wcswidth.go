// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package wcswidth

import (
	"fmt"
	"strconv"
	"strings"

	"kitty/tools/utils"
)

var _ = fmt.Print

func IsFlagCodepoint(ch rune) bool {
	return 0x1F1E6 <= ch && ch <= 0x1F1FF
}

func IsFlagPair(a rune, b rune) bool {
	return IsFlagCodepoint(a) && IsFlagCodepoint(b)
}

type ecparser_state uint8

type WCWidthIterator struct {
	prev_ch                   rune
	prev_width, current_width int
	parser                    EscapeCodeParser
	state                     ecparser_state
	rune_count                uint
}

func CreateWCWidthIterator() *WCWidthIterator {
	var ans WCWidthIterator
	ans.parser.HandleRune = ans.handle_rune
	ans.parser.HandleCSI = ans.handle_csi
	return &ans
}

func (self *WCWidthIterator) Reset() {
	self.prev_ch = 0
	self.prev_width = 0
	self.current_width = 0
	self.rune_count = 0
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
	return nil
}

func (self *WCWidthIterator) handle_rune(ch rune) error {
	self.rune_count += 1
	const (
		normal            ecparser_state = 0
		flag_pair_started ecparser_state = 3
	)
	switch self.state {
	case flag_pair_started:
		self.state = normal
		if IsFlagPair(self.prev_ch, ch) {
			break
		}
		fallthrough
	case normal:
		switch ch {
		case 0xfe0f:
			if IsEmojiPresentationBase(self.prev_ch) && self.prev_width == 1 {
				self.current_width += 1
				self.prev_width = 2
			} else {
				self.prev_width = 0
			}
		case 0xfe0e:
			if IsEmojiPresentationBase(self.prev_ch) && self.prev_width == 2 {
				self.current_width -= 1
				self.prev_width = 1
			} else {
				self.prev_width = 0
			}
		default:
			if IsFlagCodepoint(ch) {
				self.state = flag_pair_started
			}
			w := Runewidth(ch)
			switch w {
			case -1:
			case 0:
				self.prev_width = 0
			case 2:
				self.prev_width = 2
			default:
				self.prev_width = 1
			}
			self.current_width += self.prev_width
		}
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
