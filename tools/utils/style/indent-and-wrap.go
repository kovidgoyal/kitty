// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"fmt"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
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
			return strconv.Itoa(base + 60 + n - 8)
		}
		return fmt.Sprintf("%d:5:%d", base+8, n)
	}
	return fmt.Sprintf("%d:2:%d:%d:%d", base+8, self.color.Red, self.color.Green, self.color.Blue)
}

func as_uint8(x int) uint8 {
	return uint8(uint(x) & 0xff)
}

// The limits used by the kitty CSI parser in vt-parser.c
const (
	max_csi_params = 256
	max_csi_digits = 16
)

// Splits the body of a CSI SGR escape code into its parameters, mirroring
// csi_parse_loop() in kitty/vt-parser.c. An empty field terminated by a
// semicolon is zero, while an empty field terminated by a colon or the end of
// the code is dropped. is_sub_param[i] is true when params[i] was preceded by a
// colon. Returns ok == false if the code is not a plain SGR code, for example
// because it has a private or intermediate byte or an invalid character, in
// which case the terminal ignores it.
func parse_csi_params(raw string) (params []int, is_sub_param []bool, ok bool) {
	params = make([]int, 0, 16)
	is_sub_param = make([]bool, 0, 16)
	next_is_sub_param := false
	var accumulator uint64
	num_digits, mult := 0, int64(1)
	commit := func() bool {
		if num_digits == 0 {
			return true
		}
		if len(params) >= max_csi_params {
			return false
		}
		// The C parser stores into an int, truncating to 32 bits
		params = append(params, int(int32(mult*int64(accumulator))))
		is_sub_param = append(is_sub_param, next_is_sub_param)
		accumulator, num_digits, mult = 0, 0, 1
		return true
	}
	for i := 0; i < len(raw); i++ {
		switch ch := raw[i]; {
		case '0' <= ch && ch <= '9':
			if num_digits < max_csi_digits {
				num_digits++
				accumulator = accumulator*10 + uint64(ch-'0')
			}
		case ch == ':':
			// A colon is not valid as the first character of a CSI code
			if i == 0 || !commit() {
				return nil, nil, false
			}
			next_is_sub_param = true
		case ch == ';':
			if num_digits == 0 {
				num_digits = 1 // Empty means zero
			}
			if !commit() {
				return nil, nil, false
			}
			next_is_sub_param = false
		case ch == '-' && num_digits == 0 && i < len(raw)-1:
			// A minus sign starting a parameter makes it negative. Anywhere
			// else it is an intermediate byte, so this is not an SGR code.
			mult, num_digits = -1, 1
		default:
			return nil, nil, false
		}
	}
	if !commit() {
		return nil, nil, false
	}
	return params, is_sub_param, true
}

// Mirrors parse_color() in kitty/cursor.c, returns the number of parameters consumed
func (self *sgr_color) from_params(params []int) int {
	if len(params) == 0 {
		return 0
	}
	switch params[0] {
	case 5:
		if len(params) > 1 {
			self.number = 1 + int(as_uint8(params[1]))
			return 2
		}
	case 2:
		if len(params) > 3 {
			i := 1
			if len(params) > 4 {
				// Ignore the color space id in 38:2:<id>:r:g:b
				i++
			}
			self.number = -1
			self.color.Red = as_uint8(params[i])
			self.color.Green = as_uint8(params[i+1])
			self.color.Blue = as_uint8(params[i+2])
			return i + 3
		}
	}
	return 1
}

type sgr_state struct {
	italic, reverse, bold, dim, strikethrough bool
	underline_style                           underline_style
	fg, bg, uc                                sgr_color
}

func (self *sgr_state) extended_color(code int) *sgr_color {
	switch code {
	case 48:
		return &self.bg
	case 58:
		return &self.uc
	}
	return &self.fg
}

func (self *sgr_state) reset() {
	*self = sgr_state{}
}

func (self sgr_state) as_sgr(for_close bool) string {
	ans := make([]byte, 0, 32)
	if for_close {
		if self.bold {
			ans = append(ans, "221;"...)
		}
		if self.dim {
			ans = append(ans, "222;"...)
		}
		if self.italic {
			ans = append(ans, "23;"...)
		}
		if self.reverse {
			ans = append(ans, "27;"...)
		}
		if self.strikethrough {
			ans = append(ans, "29;"...)
		}
		if self.underline_style != no_underline && self.underline_style != nil_underline {
			ans = append(ans, "4:0;"...)
		}
		if self.fg.number != 0 {
			ans = append(ans, "39;"...)
		}
		if self.bg.number != 0 {
			ans = append(ans, "49;"...)
		}
		if self.uc.number != 0 {
			ans = append(ans, "59;"...)
		}
	} else {
		if self.bold {
			ans = append(ans, "1;"...)
		}
		if self.dim {
			ans = append(ans, "2;"...)
		}
		if self.italic {
			ans = append(ans, "3;"...)
		}
		if self.reverse {
			ans = append(ans, "7;"...)
		}
		if self.strikethrough {
			ans = append(ans, "9;"...)
		}
		if self.underline_style != no_underline && self.underline_style != nil_underline {
			ans = append(ans, fmt.Sprintf("4:%d;", self.underline_style)...)
		}
		if q := self.fg.as_sgr(30); q != "" {
			ans = append(ans, q...)
			ans = append(ans, ';')
		}
		if q := self.bg.as_sgr(40); q != "" {
			ans = append(ans, q...)
			ans = append(ans, ';')
		}
		if q := self.uc.as_sgr(50); q != "" {
			ans = append(ans, q...)
			ans = append(ans, ';')
		}
	}
	if len(ans) > 0 {
		ans = ans[:len(ans)-1]
	}
	return utils.UnsafeBytesToString(ans)
}

func (self sgr_state) as_escape_codes(for_close bool) string {
	q := self.as_sgr(for_close)
	if q == "" {
		return q
	}
	return fmt.Sprintf("\x1b[%sm", q)
}

// Applies a group of SGR parameters, mirroring cursor_from_sgr() in
// kitty/cursor.c. When is_group is true the parameters are a single attribute
// with its sub-parameters, such as 4:3 or 38:2:r:g:b.
func (self *sgr_state) apply_sgr(params []int, is_group bool) {
	for i := 0; i < len(params); {
		attr := params[i]
		i++
		switch attr {
		case 0:
			self.reset()
		case 1:
			self.dim, self.bold = false, true
		case 221:
			self.bold = false
		case 2:
			self.dim, self.bold = true, false
		case 222:
			self.dim = false
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
		case 21:
			self.underline_style = double_underline
		case 24:
			self.underline_style = no_underline
		case 4:
			if is_group && i < len(params) {
				// Large styles are clamped to the last style and the result is
				// stored in three bits, so negative styles wrap around. The
				// unused styles 6 and 7 cannot be represented, so ignore them.
				if us := underline_style(min(params[i], int(dashed_underline)) & 7); us <= dashed_underline {
					self.underline_style = us
				}
				i++
			} else {
				self.underline_style = straight_underline
			}
		case 30, 31, 32, 33, 34, 35, 36, 37:
			self.fg.number = attr + 1 - 30
		case 90, 91, 92, 93, 94, 95, 96, 97:
			self.fg.number = attr + 1 - 82
		case 38, 48, 58:
			i += self.extended_color(attr).from_params(params[i:])
		case 39:
			self.fg.number = 0
		case 40, 41, 42, 43, 44, 45, 46, 47:
			self.bg.number = attr + 1 - 40
		case 100, 101, 102, 103, 104, 105, 106, 107:
			self.bg.number = attr + 1 - 92
		case 49:
			self.bg.number = 0
		case 59:
			self.uc.number = 0
		}
		if is_group {
			break
		}
	}
}

// Applies the body of a CSI escape code, such as "1;38:5:200m". Mirrors
// _parse_sgr() in kitty/vt-parser.c, which splits the parameters into
// attributes with sub-parameters and semicolon separated extended colors.
// As in the terminal, an invalid sub-parameter or color type discards the
// rest of the parameters, but the attributes before it remain applied.
func (self *sgr_state) apply_csi(raw string) {
	if !strings.HasSuffix(raw, "m") {
		return
	}
	params, is_sub_param, ok := parse_csi_params(raw[:len(raw)-1])
	if !ok {
		return
	}
	if len(params) == 0 {
		params, is_sub_param = []int{0}, []bool{false}
	}
	type parse_state int
	const (
		normal parse_state = iota
		sub_params
		color
		color1
		color3
	)
	state := normal
	first_param, num_params := 0, 0
	send := func() {
		if num_params > 0 {
			self.apply_sgr(params[first_param:first_param+num_params], state != normal)
			state = normal
			first_param += num_params
			num_params = 0
		}
	}
	for pos := 0; pos < len(params); pos++ {
		switch state {
		case normal:
			if is_sub_param[pos] {
				if num_params == 0 || pos == 0 {
					return
				}
				// The previous parameter starts a group of sub-parameters
				num_params--
				send()
				state = sub_params
				first_param = pos - 1
				num_params = 1
			}
			switch params[pos] {
			case 38, 48, 58:
				send()
				state = color
				first_param = pos
				num_params = 1
			default:
				num_params++
			}
		case sub_params:
			if is_sub_param[pos] {
				num_params++
			} else {
				send()
				pos--
			}
		case color:
			switch params[pos] {
			case 2:
				state = utils.IfElse(is_sub_param[pos], sub_params, color3)
			case 5:
				state = utils.IfElse(is_sub_param[pos], sub_params, color1)
			default:
				return
			}
			num_params++
		case color1:
			num_params++
			send()
		case color3:
			num_params++
			if num_params >= 5 {
				send()
			}
		}
	}
	send()
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

func (self *hyperlink_state) reset() {
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
	buf                        []byte
	cursor_pos                 int
	seen_non_space_chars       bool
	pos_of_trailing_whitespace int
}

func (self *line_builder) reset(trim_whitespace bool) string {
	ans := string(self.buf)
	if trim_whitespace && self.pos_of_trailing_whitespace > -1 {
		prefix := ans[:self.pos_of_trailing_whitespace]
		tp := strings.TrimRightFunc(prefix, is_space)
		if len(tp) != len(prefix) {
			ans = tp + ans[self.pos_of_trailing_whitespace:]
		}

	}
	self.buf = self.buf[:0]
	self.cursor_pos = 0
	self.seen_non_space_chars = false
	self.pos_of_trailing_whitespace = -1
	return ans
}

func (self *line_builder) has_space_for_width(w, max_width int) bool {
	return w+self.cursor_pos <= max_width
}

func (self *line_builder) add_space(ch rune, trim_whitespace bool) {
	if !trim_whitespace || self.seen_non_space_chars {
		self.buf = utf8.AppendRune(self.buf, ch)
		self.pos_of_trailing_whitespace = len(self.buf)
		self.cursor_pos += wcswidth.Runewidth(ch)
	}
}

func (self *line_builder) add_word(word []byte, width int) {
	self.seen_non_space_chars = true
	self.pos_of_trailing_whitespace = -1
	self.buf = append(self.buf, word...)
	self.cursor_pos += width
}

func (self *line_builder) add_indent(word string, width int) {
	if word != "" {
		self.buf = append(self.buf, word...)
		self.cursor_pos += width
	}
}

func (self *line_builder) add_escape_code(code string) {
	self.buf = append(self.buf, code...)
}

func (self *line_builder) add_escape_code2(prefix string, body []byte, suffix string) {
	self.buf = append(self.buf, prefix...)
	self.buf = append(self.buf, body...)
	self.buf = append(self.buf, suffix...)
}

type escape_code_ struct {
	prefix, body, suffix string
}

type word_builder struct {
	buf                 []byte
	escape_codes        []escape_code_
	text_start_position int
	wcswidth            *wcswidth.WCWidthIterator
}

func (self *word_builder) reset(copy_current_word func([]byte)) {
	copy_current_word(self.buf)
	self.buf = self.buf[:0]
	self.escape_codes = self.escape_codes[:0]
	self.text_start_position = 0
	self.wcswidth.Reset()
}

func (self *word_builder) is_empty() bool {
	return len(self.buf) == 0
}

func (self *word_builder) width() int {
	return self.wcswidth.CurrentWidth()
}

func (self *word_builder) add_escape_code(prefix string, body []byte, suffix string) {
	e := escape_code_{prefix: prefix, body: string(body), suffix: suffix}
	self.escape_codes = append(self.escape_codes, e)
	self.buf = append(self.buf, prefix...)
	self.buf = append(self.buf, body...)
	self.buf = append(self.buf, suffix...)
}

func (self *word_builder) has_text() bool { return self.text_start_position != 0 }

func (self *word_builder) recalculate_width() {
	self.wcswidth.Reset()
	self.wcswidth.Parse(self.buf)
}

func (self *word_builder) add_rune(ch rune) (num_bytes_written int) {
	before := len(self.buf)
	self.buf = utf8.AppendRune(self.buf, ch)
	num_bytes_written = len(self.buf) - before
	for _, b := range self.buf[before:] {
		self.wcswidth.ParseByte(b)
	}
	if self.text_start_position == 0 {
		self.text_start_position = len(self.buf)
	}
	return
}

func (self *word_builder) remove_trailing_bytes(n int) {
	self.buf = self.buf[:len(self.buf)-n]
	self.recalculate_width()
}

type wrapper struct {
	ep                  wcswidth.EscapeCodeParser
	indent              string
	width, indent_width int
	trim_whitespace     bool

	sgr                     sgr_state
	hyperlink               hyperlink_state
	current_word            word_builder
	current_line            line_builder
	lines                   []string
	ignore_lines_containing []string
}

func (self *wrapper) newline_prefix() {
	self.current_line.add_escape_code(self.sgr.as_escape_codes(true))
	self.current_line.add_escape_code(self.hyperlink.as_escape_codes(true))
	self.current_line.add_indent(self.indent, self.indent_width)
	self.current_line.add_escape_code(self.sgr.as_escape_codes(false))
	self.current_line.add_escape_code(self.hyperlink.as_escape_codes(false))
}

func (self *wrapper) append_line(line string) {
	for _, q := range self.ignore_lines_containing {
		if strings.Contains(line, q) {
			return
		}
	}
	self.lines = append(self.lines, line)
}

func (self *wrapper) end_current_line() {
	line := self.current_line.reset(self.trim_whitespace)
	if strings.HasSuffix(line, self.indent) && wcswidth.Stringwidth(line) == self.indent_width {
		line = line[:len(line)-len(self.indent)]
	}
	self.append_line(line)
	self.newline_prefix()
}

func (self *wrapper) print_word() {
	w := self.current_word.width()
	if !self.current_line.has_space_for_width(w, self.width) {
		self.end_current_line()
		w = self.current_word.width()
	}
	for _, e := range self.current_word.escape_codes {
		if e.suffix != "" {
			self.hyperlink.apply_osc(e.body)
		} else {
			self.sgr.apply_csi(e.body)
		}
	}
	self.current_word.reset(func(word []byte) {
		self.current_line.add_word(word, w)
	})
}

func is_space(ch rune) bool {
	return ch != 0xa0 && unicode.IsSpace(ch)
}

func (self *wrapper) handle_rune(ch rune) error {
	if ch == '\n' {
		self.print_word()
		self.end_current_line()
	} else if is_space(ch) {
		if self.current_word.has_text() {
			self.print_word()
		}
		if self.current_line.cursor_pos >= self.width {
			self.end_current_line()
		}
		self.current_line.add_space(ch, self.trim_whitespace)
	} else {
		num_of_bytes_written := self.current_word.add_rune(ch)
		if self.current_word.width() > self.width {
			self.current_word.remove_trailing_bytes(num_of_bytes_written)
			self.print_word()
			return self.handle_rune(ch)
		}
	}
	return nil
}

func (self *wrapper) handle_csi(raw []byte) error {
	self.current_word.add_escape_code("\x1b[", raw, "")
	return nil
}

func (self *wrapper) handle_osc(raw []byte) error {
	self.current_word.add_escape_code("\x1b]", raw, "\x1b\\")
	return nil
}

func (self *wrapper) wrap_text(text string) []string {
	if text == "" {
		return []string{""}
	}
	self.current_line.reset(self.trim_whitespace)
	self.current_word.reset(func([]byte) {})
	self.lines = self.lines[:0]
	self.current_line.add_indent(self.indent, self.indent_width)
	self.ep.ParseString(text)
	if !self.current_word.is_empty() {
		self.print_word()
	}
	self.end_current_line()
	last_line := self.current_line.reset(self.trim_whitespace)
	self.newline_prefix()
	if last_line == self.current_line.reset(self.trim_whitespace) {
		last_line = ""
	}
	if last_line != "" {
		self.append_line(last_line)
	}
	return self.lines
}

func new_wrapper(opts WrapOptions, width int) *wrapper {
	width = max(2, width)
	ans := wrapper{indent: opts.Indent, width: width, trim_whitespace: opts.Trim_whitespace, indent_width: wcswidth.Stringwidth(opts.Indent)}
	if opts.Ignore_lines_containing != "" {
		ans.ignore_lines_containing = utils.Splitlines(opts.Ignore_lines_containing)
	}
	ans.ep.HandleRune = ans.handle_rune
	ans.ep.HandleCSI = ans.handle_csi
	ans.ep.HandleOSC = ans.handle_osc
	ans.lines = make([]string, 0, 32)
	ans.current_word.escape_codes = make([]escape_code_, 0, 8)
	ans.current_word.wcswidth = wcswidth.CreateWCWidthIterator()
	return &ans
}

type WrapOptions struct {
	Ignore_lines_containing string
	Trim_whitespace         bool   // trim whitespace at the start and end of lines (start is after indent).
	Indent                  string // indent to add at the start of every line all formatting is cleared for the indent.
}

func WrapTextAsLines(text string, width int, opts WrapOptions) []string {
	w := new_wrapper(opts, width)
	return w.wrap_text(text)
}

func WrapText(text string, width int, opts WrapOptions) string {
	return strings.Join(WrapTextAsLines(text, width, opts), "\n")
}
