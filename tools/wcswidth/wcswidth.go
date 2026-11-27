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
	// Whether the last rune was added to the cell before it, rather than starting a new cell
	combined   bool
	parser     EscapeCodeParser
	rune_count uint
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
	self.combined = false
	self.seg = 0
	self.parser.Reset()
}

func (self *WCWidthIterator) handle_csi(csi []byte) error {
	if len(csi) > 1 && csi[len(csi)-1] == 'b' {
		num_string := utils.UnsafeBytesToString(csi[:len(csi)-1])
		n, err := strconv.Atoi(num_string)
		if err == nil && n > 0 {
			for range n {
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
	self.combined = false
	cp := CharPropsFor(ch)
	if cp.Is_invalid() == 1 {
		// As in the terminal, invalid chars, which include control chars, are
		// ignored, except for the ones that move the cursor, after which there
		// is no previous cell to combine with
		switch ch {
		case '\b', '\t', '\n', '\v', '\f', '\r':
			self.prev_width = 0
			self.can_combine = false
			self.seg = 0
			self.prev_ch = ch
		}
		return nil
	}
	self.seg = self.seg.Step(cp)
	if self.can_combine && self.seg.Add_to_current_cell() == 1 {
		self.combined = true
		switch ch {
		// A variation selector that does not apply leaves the width of the cell unchanged
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
		default:
			if cp.Spacing_width() > 0 {
				// A spacing mark widens the cell it is added to, or is in a cell of its
				// own when there is no previous cell
				w := CellWidthWithSpacingMark(self.prev_width, cp)
				self.current_width += w - self.prev_width
				self.prev_width = w
			}
		}
	} else {
		switch cp.Width() {
		case 0:
			// A zero width char after a grapheme boundary is added to the previous cell, if there is
			// one, otherwise it is discarded, unless it is a spacing mark, which is then in a cell of its own
			self.combined = self.can_combine
			if cp.Spacing_width() > 0 {
				prev := 0
				if self.can_combine {
					prev = self.prev_width
				}
				w := CellWidthWithSpacingMark(prev, cp)
				self.current_width += w - prev
				self.prev_width = w
			} else if !self.can_combine {
				self.prev_width = 0
			}
		case 2:
			self.prev_width = 2
			self.current_width += 2
		default:
			self.prev_width = 1
			self.current_width += 1
		}
		self.can_combine = true
	}
	self.prev_ch = ch
	return nil
}

// The maximum width in cells that spacing marks can widen a cell to, see the
// Spacing marks section of docs/text-sizing-protocol.rst
const MAX_SPACING_MARK_CELL_WIDTH = 4

// The width of a cell of width cell_width after spacing_mark is added to it. A
// cell of width zero means there is no previous cell, so the mark is in a cell
// of its own.
func CellWidthWithSpacingMark(cell_width int, spacing_mark CharProps) int {
	if cell_width >= MAX_SPACING_MARK_CELL_WIDTH {
		return cell_width
	}
	return min(MAX_SPACING_MARK_CELL_WIDTH, cell_width+int(spacing_mark.Spacing_width()))
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
