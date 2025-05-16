// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"fmt"
	"strconv"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

type escape_code interface {
	prefix() string
	suffix() string
	is_empty() bool
}

// bool values {{{
type bool_value struct {
	is_set, val bool
}

func (self bool_value) as_sgr(start, end string, prefix, suffix []string) ([]string, []string) {
	if self.is_set {
		if !self.val {
			start, end = end, start
		}
		prefix = append(prefix, start)
		suffix = append(suffix, end)
	}
	return prefix, suffix
}

func (self *bool_value) set_val(val bool) {
	self.is_set = true
	self.val = val
}

func (self *bool_value) from_string(raw string) bool {
	switch strings.ToLower(raw) {
	case "y", "yes", "true", "1":
		self.set_val(true)
		return true
	case "n", "no", "false", "0":
		self.set_val(false)
		return true
	default:
		return false
	}
}

// }}}

// color values {{{
type RGBA struct {
	Red, Green, Blue, Inverse_alpha uint8
}

func (self RGBA) AsRGBSharp() string {
	return fmt.Sprintf("#%02x%02x%02x", self.Red, self.Green, self.Blue)
}

func (self *RGBA) parse_rgb_strings(r string, g string, b string) bool {
	var rv, gv, bv uint64
	var err error
	if rv, err = strconv.ParseUint(r, 16, 8); err != nil {
		return false
	}
	if gv, err = strconv.ParseUint(g, 16, 8); err != nil {
		return false
	}
	if bv, err = strconv.ParseUint(b, 16, 8); err != nil {
		return false
	}
	self.Red, self.Green, self.Blue = uint8(rv), uint8(gv), uint8(bv)
	return true
}

func (self *RGBA) AsRGB() uint32 {
	return uint32(self.Blue) | (uint32(self.Green) << 8) | (uint32(self.Red) << 16)
}

func (self *RGBA) IsDark() bool {
	return self.Red < 155 && self.Green < 155 && self.Blue < 155
}

func (self *RGBA) FromRGB(col uint32) {
	self.Red = uint8((col >> 16) & 0xff)
	self.Green = uint8((col >> 8) & 0xff)
	self.Blue = uint8((col) & 0xff)
}

type color_type struct {
	is_numbered bool
	val         RGBA
}

func (self color_type) as_sgr(number_base int, prefix, suffix []string) ([]string, []string) {
	suffix = append(suffix, strconv.Itoa(number_base+9))
	if self.is_numbered {
		num := int(self.val.Red)
		if num < 16 && number_base < 50 {
			if num > 7 {
				number_base += 60
				num -= 8
			}
			prefix = append(prefix, strconv.Itoa(number_base+num))
		} else {
			prefix = append(prefix, fmt.Sprintf("%d:5:%d", number_base+8, num))
		}
	} else {
		prefix = append(prefix, fmt.Sprintf("%d:2:%d:%d:%d", number_base+8, self.val.Red, self.val.Green, self.val.Blue))
	}
	return prefix, suffix
}

type color_value struct {
	is_set bool
	val    color_type
}

func parse_sharp(color string) (ans RGBA, err error) {
	if len(color)%3 != 0 {
		return RGBA{}, fmt.Errorf("Not a valid color: #%s", color)
	}
	part_size := len(color) / 3
	r, g, b := color[:part_size], color[part_size:2*part_size], color[part_size*2:]
	if part_size == 1 {
		r += r
		g += g
		b += b
	}
	if !ans.parse_rgb_strings(r, g, b) {
		err = fmt.Errorf("Not a valid color: #%s", color)
	}
	return
}

func parse_rgb(color string) (ans RGBA, err error) {
	colors := strings.Split(color, "/")
	if len(colors) == 3 && ans.parse_rgb_strings(colors[0], colors[1], colors[2]) {
		return
	}
	err = fmt.Errorf("Not a valid RGB color: %#v", color)
	return
}

func ParseColor(color string) (RGBA, error) {
	raw := strings.TrimSpace(strings.ToLower(color))
	if val, ok := ColorNames[raw]; ok {
		return val, nil
	}
	if strings.HasPrefix(raw, "#") {
		return parse_sharp(raw[1:])
	}
	if strings.HasPrefix(raw, "rgb:") {
		return parse_rgb(raw[4:])
	}
	return RGBA{}, fmt.Errorf("Not a valid color name: %#v", color)
}

type NullableColor struct {
	Color RGBA
	IsSet bool
}

func ParseColorOrNone(color string) (NullableColor, error) {
	raw := strings.TrimSpace(strings.ToLower(color))
	if raw == "none" {
		return NullableColor{}, nil
	}
	c, err := ParseColor(raw)
	return NullableColor{Color: c, IsSet: err == nil}, err
}

var named_colors = map[string]uint8{
	"black": 0, "red": 1, "green": 2, "yellow": 3, "blue": 4, "magenta": 5, "cyan": 6, "gray": 7, "white": 7,

	"hi-black": 8, "hi-red": 9, "hi-green": 10, "hi-yellow": 11, "hi-blue": 12, "hi-magenta": 13, "hi-cyan": 14, "hi-gray": 15, "hi-white": 15,

	"bright-black": 8, "bright-red": 9, "bright-green": 10, "bright-yellow": 11, "bright-blue": 12, "bright-magenta": 13, "bright-cyan": 14, "bright-gray": 15, "bright-white": 15,

	"intense-black": 8, "intense-red": 9, "intense-green": 10, "intense-yellow": 11, "intense-blue": 12, "intense-magenta": 13, "intense-cyan": 14, "intense-gray": 15, "intense-white": 15,
}

func (self *color_value) from_string(raw string) bool {
	if n, ok := named_colors[raw]; ok {
		self.is_set = true
		self.val = color_type{val: RGBA{Red: n}, is_numbered: true}
		return true
	}
	a, err := strconv.Atoi(raw)
	if err == nil && 0 <= a && a <= 255 {
		self.is_set = true
		self.val = color_type{val: RGBA{Red: uint8(a)}, is_numbered: true}
		return true
	}
	c, err := ParseColor(raw)
	if err != nil {
		return false
	}
	self.is_set = true
	self.val = color_type{val: c}
	return true
}

func (self color_value) as_sgr(number_base int, prefix, suffix []string) ([]string, []string) {
	if self.is_set {
		prefix, suffix = self.val.as_sgr(number_base, prefix, suffix)
	}
	return prefix, suffix
}

// }}}

// underline values {{{
type underline_style uint8

const (
	no_underline       underline_style = 0
	straight_underline underline_style = 1
	double_underline   underline_style = 2
	curly_underline    underline_style = 3
	dotted_underline   underline_style = 4
	dashed_underline   underline_style = 5

	nil_underline underline_style = 255
)

type underline_value struct {
	is_set bool
	style  underline_style
}

func (self *underline_value) from_string(val string) bool {
	ans := nil_underline
	switch val {
	case "true", "yes", "y", "straight", "single":
		ans = straight_underline
	case "false", "no", "n", "none":
		ans = no_underline
	case "double":
		ans = double_underline
	case "curly":
		ans = curly_underline
	case "dotted":
		ans = dotted_underline
	case "dashed":
		ans = dashed_underline
	}
	if ans == nil_underline {
		return false
	}
	self.is_set = true
	self.style = ans
	return true
}

func (self underline_value) as_sgr(prefix, suffix []string) ([]string, []string) {
	if self.is_set {
		s, e := "4:0", "4:0"
		if self.style != no_underline {
			s = "4:" + strconv.Itoa(int(self.style))
		}
		prefix = append(prefix, s)
		suffix = append(suffix, e)
	}
	return prefix, suffix
}

// }}}

type sgr_code struct {
	bold, italic, reverse, dim, strikethrough bool_value
	fg, bg, uc                                color_value
	underline                                 underline_value

	_prefix, _suffix string
}

func (self sgr_code) prefix() string {
	return self._prefix
}

func (self sgr_code) suffix() string {
	return self._suffix
}

func (self sgr_code) is_empty() bool {
	return self._prefix == ""
}

type url_code struct {
	url string
}

func (self url_code) prefix() string {
	return fmt.Sprintf("\x1b]8;;%s\x1b\\", self.url)
}

func (self url_code) suffix() string {
	return "\x1b]8;;\x1b\\"
}

func (self url_code) is_empty() bool {
	return self.url == ""
}

func (self *sgr_code) update() {
	p := make([]string, 0, 1)
	s := make([]string, 0, 1)
	p, s = self.bold.as_sgr("1", "221", p, s)
	p, s = self.dim.as_sgr("2", "222", p, s)
	p, s = self.italic.as_sgr("3", "23", p, s)
	p, s = self.reverse.as_sgr("7", "27", p, s)
	p, s = self.strikethrough.as_sgr("9", "29", p, s)
	p, s = self.underline.as_sgr(p, s)
	p, s = self.fg.as_sgr(30, p, s)
	p, s = self.bg.as_sgr(40, p, s)
	p, s = self.uc.as_sgr(50, p, s)
	if len(p) > 0 {
		self._prefix = "\x1b[" + strings.Join(p, ";") + "m"
	} else {
		self._prefix = ""
	}
	if len(s) > 0 {
		self._suffix = "\x1b[" + strings.Join(s, ";") + "m"
	} else {
		self._suffix = ""
	}
}

func parse_spec(spec string) []escape_code {
	ans := make([]escape_code, 0, 1)
	sgr := sgr_code{}
	sparts, _ := shlex.Split(spec)
	for _, p := range sparts {
		key, val, found := strings.Cut(p, "=")
		if !found {
			val = "true"
		}
		switch key {
		case "fg":
			sgr.fg.from_string(val)
		case "bg":
			sgr.bg.from_string(val)
		case "bold", "b":
			sgr.bold.from_string(val)
		case "italic", "i":
			sgr.italic.from_string(val)
		case "reverse":
			sgr.reverse.from_string(val)
		case "dim", "faint":
			sgr.dim.from_string(val)
		case "underline", "u":
			sgr.underline.from_string(val)
		case "strikethrough", "s":
			sgr.strikethrough.from_string(val)
		case "ucol", "underline_color", "uc":
			sgr.uc.from_string(val)
		}
	}
	sgr.update()
	if !sgr.is_empty() {
		ans = append(ans, &sgr)
	}
	return ans
}

var parsed_spec_cache = make(map[string][]escape_code)
var parsed_spec_cache_mutex = sync.Mutex{}

func cached_parse_spec(spec string) []escape_code {
	parsed_spec_cache_mutex.Lock()
	defer parsed_spec_cache_mutex.Unlock()
	if val, ok := parsed_spec_cache[spec]; ok {
		return val
	}
	ans := parse_spec(spec)
	parsed_spec_cache[spec] = ans
	return ans
}

func prefix_for_spec(spec string) string {
	sb := strings.Builder{}
	for _, ec := range cached_parse_spec(spec) {
		sb.WriteString(ec.prefix())
	}
	return sb.String()
}

func suffix_for_spec(spec string) string {
	sb := strings.Builder{}
	for _, ec := range cached_parse_spec(spec) {
		sb.WriteString(ec.suffix())
	}
	return sb.String()
}
