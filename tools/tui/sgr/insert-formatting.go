// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package sgr

import (
	"fmt"
	"slices"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
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
		self.Red, self.Green, self.Blue = v.Red, v.Green, v.Blue
	case string:
		rgba, err := style.ParseColor(v)
		if err != nil {
			return err
		}
		self.Is_numbered = false
		self.Red, self.Green, self.Blue = rgba.Red, rgba.Green, rgba.Blue
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

func as_uint8(x int) uint8 {
	return uint8(uint(x) & 0xff)
}

func (self *Color) FromExtended(nums ...int) bool {
	switch nums[0] {
	case 5:
		if len(nums) > 1 {
			self.Red = as_uint8(nums[1])
			self.Is_numbered = true
			return true
		}
	case 2:
		if len(nums) > 3 {
			self.Is_numbered = false
			self.Red, self.Green, self.Blue = as_uint8(nums[1]), as_uint8(nums[2]), as_uint8(nums[3])
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

func (self *BoolVal) AsCSI(set, reset string) string {
	if !self.Is_set {
		return ""
	}
	if self.Val {
		return set
	}
	return reset
}

func (self *UnderlineStyleVal) AsCSI() string {
	if !self.Is_set {
		return ""
	}
	return fmt.Sprintf("4:%d;", self.Val)
}

func (self *ColorVal) AsCSI(base int) string {
	if !self.Is_set {
		return ""
	}
	if self.Is_default {
		return strconv.Itoa(base + 9)
	}
	return self.Val.AsCSI(base)
}

func (self *SGR) AsCSI() string {
	ans := make([]byte, 0, 16)
	w := func(x string) {
		if x != "" {
			ans = append(ans, x...)
			ans = append(ans, ';')
		}
	}
	w(self.Bold.AsCSI("1", "221"))
	w(self.Dim.AsCSI("2", "222"))
	w(self.Italic.AsCSI("3", "23"))
	w(self.Reverse.AsCSI("7", "27"))
	w(self.Strikethrough.AsCSI("9", "29"))
	w(self.Underline_style.AsCSI())
	w(self.Foreground.AsCSI(30))
	w(self.Background.AsCSI(40))
	w(self.Underline_color.AsCSI(50))

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
			ans.Bold.Val, ans.Bold.Is_set = true, true
		case 221:
			ans.Bold.Val, ans.Bold.Is_set = false, true
		case 2:
			ans.Dim.Val, ans.Dim.Is_set = true, true
		case 222:
			ans.Dim.Val, ans.Dim.Is_set = false, true
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
	Offset, Size             int // in bytes
	opening_sgr, closing_sgr SGR
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
	self.opening_sgr.Foreground.Set(val)
	return self
}

func (self *Span) SetBackground(val any) *Span {
	self.opening_sgr.Background.Set(val)
	return self
}

func (self *Span) SetUnderlineColor(val any) *Span {
	self.opening_sgr.Underline_color.Set(val)
	return self
}

func (self *Span) SetItalic(val bool) *Span {
	self.opening_sgr.Italic.Set(val)
	return self
}

func (self *Span) SetBold(val bool) *Span {
	self.opening_sgr.Bold.Set(val)
	return self
}
func (self *Span) SetReverse(val bool) *Span {
	self.opening_sgr.Reverse.Set(val)
	return self
}
func (self *Span) SetDim(val bool) *Span {
	self.opening_sgr.Dim.Set(val)
	return self
}
func (self *Span) SetStrikethrough(val bool) *Span {
	self.opening_sgr.Strikethrough.Set(val)
	return self
}
func (self *Span) SetUnderlineStyle(val UnderlineStyle) *Span {
	self.opening_sgr.Underline_style.Is_set = true
	self.opening_sgr.Underline_style.Val = val
	return self
}

func (self *Span) SetClosingForeground(val any) *Span {
	self.closing_sgr.Foreground.Set(val)
	return self
}

func (self *Span) SetClosingBackground(val any) *Span {
	self.closing_sgr.Background.Set(val)
	return self
}

func (self *Span) SetClosingUnderlineColor(val any) *Span {
	self.closing_sgr.Underline_color.Set(val)
	return self
}

func (self *Span) SetClosingItalic(val bool) *Span {
	self.closing_sgr.Italic.Set(val)
	return self
}

func (self *Span) SetClosingBold(val bool) *Span {
	self.closing_sgr.Bold.Set(val)
	return self
}
func (self *Span) SetClosingReverse(val bool) *Span {
	self.closing_sgr.Reverse.Set(val)
	return self
}
func (self *Span) SetClosingDim(val bool) *Span {
	self.closing_sgr.Dim.Set(val)
	return self
}
func (self *Span) SetClosingStrikethrough(val bool) *Span {
	self.closing_sgr.Strikethrough.Set(val)
	return self
}
func (self *Span) SetClosingUnderlineStyle(val UnderlineStyle) *Span {
	self.closing_sgr.Underline_style.Is_set = true
	self.opening_sgr.Underline_style.Val = val
	return self
}

// Insert formatting into text at the specified offsets, overriding any existing formatting, and restoring
// existing formatting after the replaced sections.
func InsertFormatting(text string, spans ...*Span) string {
	spans = utils.Filter(spans, func(s *Span) bool { return !s.opening_sgr.IsEmpty() })
	if len(spans) == 0 {
		return text
	}
	var in_span *Span
	ans := make([]byte, 0, 2*len(text))
	var overall_sgr_state SGR
	slices.SortFunc(spans, func(a, b *Span) int { return a.Offset - b.Offset })
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
			write_csi(in_span.opening_sgr.AsCSI())
		} else {
			in_span = nil
		}

	}

	close_span := func() {
		write_csi(in_span.closing_sgr.AsCSI())
		write_csi(overall_sgr_state.AsCSI())
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
				sgr.ApplyMask(in_span.opening_sgr)
				csi := sgr.AsCSI()
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
