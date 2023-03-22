// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package sgr

import (
	"fmt"
	"strconv"
	"strings"
	"unicode/utf8"

	"kitty/tools/utils"
	"kitty/tools/utils/style"
	"kitty/tools/wcswidth"

	"golang.org/x/exp/slices"
)

var _ = fmt.Print

type UnderlineStyle uint8

const (
	No_underline UnderlineStyle = iota
	Straight_underline
	Double_underline
	Curly_underline
	Dotted_underline
	Dashed_underline
)

type Color struct {
	Red, Green, Blue uint8
	Is_numbered      bool
}

func (self *Color) Set(val any) (err error) {
	switch v := val.(type) {
	case int:
		self.Is_numbered = true
		self.Red = uint8(v)
	case style.RGBA:
		self.Is_numbered = false
		self.Red, self.Green, self.Blue = v.Red, v.Red, v.Blue
	case string:
		rgba, err := style.ParseColor(v)
		if err != nil {
			return err
		}
		self.Is_numbered = false
		self.Red, self.Green, self.Blue = rgba.Red, rgba.Red, rgba.Blue
	default:
		return fmt.Errorf("Unknown type to set color from: %T", v)
	}
	return nil
}

func (self Color) AsCSI(base int) string {
	if self.Is_numbered && base < 50 {
		if self.Red < 8 {
			return strconv.Itoa(base + int(self.Red))
		}
		if self.Red < 16 {
			return strconv.Itoa(base + 52 + int(self.Red))
		}
		return fmt.Sprintf("%d:5:%d", base+8, self.Red)
	}
	return fmt.Sprintf("%d:2:%d:%d:%d", base+8, self.Red, self.Green, self.Blue)
}

func (self *Color) FromNumber(n uint8) {
	self.Is_numbered, self.Red = true, n
}

func (self *Color) FromExtended(nums ...int) bool {
	switch nums[0] {
	case 5:
		if len(nums) > 1 {
			self.Red = uint8(nums[1])
			self.Is_numbered = true
			return true
		}
	case 2:
		if len(nums) > 3 {
			self.Is_numbered = false
			self.Red, self.Green, self.Blue = uint8(nums[1]), uint8(nums[2]), uint8(nums[3])
			return true
		}
	}
	return false
}

type BoolVal struct{ Is_set, Val bool }

type UnderlineStyleVal struct {
	Is_set bool
	Val    UnderlineStyle
}
type ColorVal struct {
	Is_set, Is_default bool
	Val                Color
}

type SGR struct {
	Italic, Reverse, Bold, Dim, Strikethrough BoolVal
	Underline_style                           UnderlineStyleVal
	Foreground, Background, Underline_color   ColorVal
}

func (self *SGR) AsCSI(for_close bool) string {
	ans := make([]byte, 0, 16)
	if for_close {
		if self.Bold.Is_set || self.Dim.Is_set {
			ans = append(ans, '2', '2', ';')
		}
		if self.Italic.Is_set {
			ans = append(ans, '2', '3', ';')
		}
		if self.Reverse.Is_set {
			ans = append(ans, '2', '7', ';')
		}
		if self.Strikethrough.Is_set {
			ans = append(ans, '2', '9', ';')
		}
		if self.Underline_style.Is_set {
			ans = append(ans, '4', ':', '0', ';')
		}
		if self.Foreground.Is_set {
			ans = append(ans, '3', '9', ';')
		}
		if self.Background.Is_set {
			ans = append(ans, '4', '9', ';')
		}
		if self.Underline_color.Is_set {
			ans = append(ans, '5', '9', ';')
		}
	} else {
		if self.Bold.Is_set {
			ans = append(ans, '1', ';')
		}
		if self.Dim.Is_set {
			ans = append(ans, '2', ';')
		}
		if self.Italic.Is_set {
			ans = append(ans, '3', ';')
		}
		if self.Reverse.Is_set {
			ans = append(ans, '7', ';')
		}
		if self.Strikethrough.Is_set {
			ans = append(ans, '9', ';')
		}
		if self.Underline_style.Is_set {
			ans = append(ans, fmt.Sprintf("4:%d;", self.Underline_style.Val)...)
		}
		if self.Foreground.Is_set {
			if self.Foreground.Is_default {
				ans = append(ans, '3', '9', ';')
			} else {
				ans = append(ans, self.Foreground.Val.AsCSI(30)...)
				ans = append(ans, ';')
			}
		}
		if self.Background.Is_set {
			if self.Background.Is_default {
				ans = append(ans, '4', '9', ';')
			} else {
				ans = append(ans, self.Background.Val.AsCSI(40)...)
				ans = append(ans, ';')
			}
		}
		if self.Underline_color.Is_set {
			if self.Underline_color.Is_default {
				ans = append(ans, '5', '9', ';')
			} else {
				ans = append(ans, self.Underline_color.Val.AsCSI(50)...)
				ans = append(ans, ';')
			}
		}
	}

	if len(ans) > 0 {
		ans = ans[:len(ans)-1]
		ans = append(ans, 'm')
	}
	return utils.UnsafeBytesToString(ans)
}

func (self *SGR) IsEmpty() bool {
	return !(self.Foreground.Is_set || self.Background.Is_set || self.Underline_color.Is_set || self.Underline_style.Is_set || self.Italic.Is_set || self.Bold.Is_set || self.Reverse.Is_set || self.Dim.Is_set || self.Strikethrough.Is_set)
}

func (self *SGR) ApplyMask(other SGR) {
	if other.Italic.Is_set {
		self.Italic.Is_set = false
	}
	if other.Reverse.Is_set {
		self.Reverse.Is_set = false
	}
	if other.Bold.Is_set {
		self.Bold.Is_set = false
	}
	if other.Dim.Is_set {
		self.Dim.Is_set = false
	}
	if other.Strikethrough.Is_set {
		self.Strikethrough.Is_set = false
	}
	if other.Underline_style.Is_set {
		self.Underline_style.Is_set = false
	}
	if other.Foreground.Is_set {
		self.Foreground.Is_set = false
	}
	if other.Background.Is_set {
		self.Background.Is_set = false
	}
	if other.Underline_color.Is_set {
		self.Underline_color.Is_set = false
	}
}

func (self *SGR) ApplySGR(other SGR) {
	if other.Italic.Is_set {
		self.Italic = other.Italic
	}
	if other.Reverse.Is_set {
		self.Reverse = other.Reverse
	}
	if other.Bold.Is_set {
		self.Bold = other.Bold
	}
	if other.Dim.Is_set {
		self.Dim = other.Dim
	}
	if other.Strikethrough.Is_set {
		self.Strikethrough = other.Strikethrough
	}
	if other.Underline_style.Is_set {
		self.Underline_style = other.Underline_style
	}
	if other.Foreground.Is_set {
		self.Foreground = other.Foreground
	}
	if other.Background.Is_set {
		self.Background = other.Background
	}
	if other.Underline_color.Is_set {
		self.Underline_color = other.Underline_color
	}
}

func SGRFromCSI(csi string) (ans SGR) {
	if !strings.HasSuffix(csi, "m") {
		return
	}
	csi = csi[:len(csi)-1]
	if csi == "" {
		csi = "0"
	}
	parts := strings.Split(csi, ";")
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
			ans = SGR{}
		case 1:
			ans.Dim.Val, ans.Bold.Val = false, true
			ans.Dim.Is_set, ans.Bold.Is_set = true, true
		case 2:
			ans.Dim.Val, ans.Bold.Val = true, false
			ans.Dim.Is_set, ans.Bold.Is_set = true, true
		case 22:
			ans.Dim.Val, ans.Bold.Val = false, false
			ans.Dim.Is_set, ans.Bold.Is_set = true, true
		case 3:
			ans.Italic.Is_set, ans.Italic.Val = true, true
		case 23:
			ans.Italic.Is_set, ans.Italic.Val = true, false
		case 7:
			ans.Reverse.Is_set, ans.Reverse.Val = true, true
		case 27:
			ans.Reverse.Is_set, ans.Reverse.Val = true, false
		case 9:
			ans.Strikethrough.Is_set, ans.Strikethrough.Val = true, true
		case 29:
			ans.Strikethrough.Is_set, ans.Strikethrough.Val = true, false
		case 24:
			ans.Underline_style.Is_set, ans.Underline_style.Val = true, No_underline
		case 4:
			us := 1
			if len(nums) > 1 {
				us = nums[1]
			}
			switch us {
			case 0:
				ans.Underline_style.Is_set, ans.Underline_style.Val = true, No_underline
			case 1:
				ans.Underline_style.Is_set, ans.Underline_style.Val = true, Straight_underline
			case 2:
				ans.Underline_style.Is_set, ans.Underline_style.Val = true, Double_underline
			case 3:
				ans.Underline_style.Is_set, ans.Underline_style.Val = true, Curly_underline
			case 4:
				ans.Underline_style.Is_set, ans.Underline_style.Val = true, Dotted_underline
			case 5:
				ans.Underline_style.Is_set, ans.Underline_style.Val = true, Dashed_underline
			}
		case 30, 31, 32, 33, 34, 35, 36, 37:
			ans.Foreground.Is_set, ans.Foreground.Is_default = true, false
			ans.Foreground.Val.FromNumber(uint8(nums[0] - 30))
		case 90, 91, 92, 93, 94, 95, 96, 97:
			ans.Foreground.Is_set, ans.Foreground.Is_default = true, false
			ans.Foreground.Val.FromNumber(uint8(nums[0] - 82))
		case 38:
			if ans.Foreground.Val.FromExtended(nums[1:]...) {
				ans.Foreground.Is_set, ans.Foreground.Is_default = true, false
			}
		case 39:
			ans.Foreground.Is_set, ans.Foreground.Is_default = true, true
		case 40, 41, 42, 43, 44, 45, 46, 47:
			ans.Background.Is_set, ans.Background.Is_default = true, false
			ans.Background.Val.FromNumber(uint8(nums[0] - 40))
		case 100, 101, 102, 103, 104, 105, 106, 107:
			ans.Background.Is_set, ans.Background.Is_default = true, false
			ans.Background.Val.FromNumber(uint8(nums[0] - 92))
		case 48:
			if ans.Background.Val.FromExtended(nums[1:]...) {
				ans.Background.Is_set, ans.Background.Is_default = true, false
			}
		case 49:
			ans.Background.Is_set, ans.Background.Is_default = true, true
		case 58:
			if ans.Underline_color.Val.FromExtended(nums[1:]...) {
				ans.Underline_color.Is_set, ans.Underline_color.Is_default = true, false
			}
		case 59:
			ans.Underline_color.Is_set, ans.Underline_color.Is_default = true, true
		}
	}

	return
}

type Span struct {
	Offset, Size int // in bytes
	SGR          SGR
}

func NewSpan(offset, size int) *Span {
	return &Span{Offset: offset, Size: size}
}

func (self *BoolVal) Set(val bool) {
	self.Is_set = true
	self.Val = val
}

func (self *ColorVal) Set(val any) {
	self.Is_set = true
	if val == nil {
		self.Is_default = true
	} else {
		self.Is_default = false
		if err := self.Val.Set(val); err != nil {
			panic(err)
		}
	}
}

func (self *Span) SetForeground(val any) *Span {
	self.SGR.Foreground.Set(val)
	return self
}

func (self *Span) SetBackground(val any) *Span {
	self.SGR.Background.Set(val)
	return self
}

func (self *Span) SetUnderlineColor(val any) *Span {
	self.SGR.Underline_color.Set(val)
	return self
}

func (self *Span) SetItalic(val bool) *Span {
	self.SGR.Italic.Set(val)
	return self
}

func (self *Span) SetBold(val bool) *Span {
	self.SGR.Bold.Set(val)
	return self
}
func (self *Span) SetReverse(val bool) *Span {
	self.SGR.Reverse.Set(val)
	return self
}
func (self *Span) SetDim(val bool) *Span {
	self.SGR.Dim.Set(val)
	return self
}
func (self *Span) SetStrikethrough(val bool) *Span {
	self.SGR.Strikethrough.Set(val)
	return self
}
func (self *Span) SetUnderlineStyle(val UnderlineStyle) *Span {
	self.SGR.Underline_style.Is_set = true
	self.SGR.Underline_style.Val = val
	return self
}

// Insert formatting into text at the specified offsets, overriding any existing formatting, and restoring
// existing formatting after the replaced sections.
func InsertFormatting(text string, spans ...*Span) string {
	var in_span *Span
	ans := make([]byte, 0, 2*len(text))
	var overall_sgr_state SGR
	slices.SortFunc(spans, func(a, b *Span) bool { return a.Offset < b.Offset })
	text_len := 0
	var ep *wcswidth.EscapeCodeParser

	write_csi := func(csi string) {
		if csi != "" {
			ans = append(ans, 0x1b, '[')
			ans = append(ans, csi...)
		}
	}
	open_span := func() {
		in_span = spans[0]
		spans = spans[1:]
		if in_span.Size > 0 {
			write_csi(in_span.SGR.AsCSI(false))
		} else {
			in_span = nil
		}

	}

	close_span := func() {
		write_csi(in_span.SGR.AsCSI(true))
		write_csi(overall_sgr_state.AsCSI(false))
		in_span = nil
	}

	ep = &wcswidth.EscapeCodeParser{
		HandleRune: func(ch rune) error {
			var rlen int
			if in_span == nil {
				if len(spans) > 0 && text_len >= spans[0].Offset {
					open_span()
					return ep.HandleRune(ch)
				}
				before := len(ans)
				ans = utf8.AppendRune(ans, ch)
				rlen = len(ans) - before
			} else {
				rlen = utf8.RuneLen(ch)
				if text_len+rlen > in_span.Offset+in_span.Size {
					close_span()
				}
				ans = utf8.AppendRune(ans, ch)
			}
			text_len += rlen
			return nil
		},
		HandleCSI: func(csib []byte) error {
			csi := utils.UnsafeBytesToString(csib)
			if len(csi) == 0 || csi[len(csi)-1] != 'm' {
				write_csi(csi)
				return nil
			}
			sgr := SGRFromCSI(csi)
			overall_sgr_state.ApplySGR(sgr)
			if in_span == nil {
				write_csi(csi)
			} else {
				sgr.ApplyMask(in_span.SGR)
				csi := sgr.AsCSI(false)
				write_csi(csi)
			}
			return nil
		},
		HandleOSC: func(osc []byte) error {
			ans = append(ans, 0x1b, ']')
			ans = append(ans, osc...)
			ans = append(ans, 0x1b, '\\')
			return nil
		},
	}
	ep.ParseString(text)
	if in_span != nil {
		close_span()
	}
	return utils.UnsafeBytesToString(ans)
}
