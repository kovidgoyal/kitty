// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package wcswidth

import (
	"bytes"
	"fmt"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type parser_state uint8
type csi_state uint8
type csi_char_type uint8

var bracketed_paste_start = []byte{'2', '0', '0', '~'}

const (
	normal parser_state = iota
	esc
	csi
	st
	st_or_bel
	esc_st
	c1_st
	bracketed_paste
)

const (
	parameter csi_state = iota
	intermediate
)

const (
	unknown_csi_char csi_char_type = iota
	parameter_csi_char
	intermediate_csi_char
	final_csi_char
)

type EscapeCodeParser struct {
	state                  parser_state
	utf8_state, utf8_codep utils.UTF8State
	csi_state              csi_state
	current_buffer         []byte
	bracketed_paste_buffer []utils.UTF8State
	current_callback       func([]byte) error

	ReplaceInvalidUtf8Bytes bool

	// Callbacks
	HandleRune                func(rune) error
	HandleEndOfBracketedPaste func() error
	HandleCSI                 func([]byte) error
	HandleOSC                 func([]byte) error
	HandleDCS                 func([]byte) error
	HandlePM                  func([]byte) error
	HandleSOS                 func([]byte) error
	HandleAPC                 func([]byte) error
}

func (self *EscapeCodeParser) InBracketedPaste() bool { return self.state == bracketed_paste }

func (self *EscapeCodeParser) ParseString(s string) error {
	return self.Parse(utils.UnsafeStringToBytes(s))
}

func (self *EscapeCodeParser) ParseByte(b byte) error {
	switch self.state {
	case normal, bracketed_paste:
		prev_utf8_state := self.utf8_state
		switch utils.DecodeUtf8(&self.utf8_state, &self.utf8_codep, b) {
		case utils.UTF8_ACCEPT:
			err := self.dispatch_char(self.utf8_codep)
			if err != nil {
				self.reset_state()
				return err
			}
		case utils.UTF8_REJECT:
			self.utf8_state = utils.UTF8_ACCEPT
			if prev_utf8_state != utils.UTF8_ACCEPT {
				// reparse this byte with state set to UTF8_ACCEPT
				return self.ParseByte(b)
			}
			if self.ReplaceInvalidUtf8Bytes {
				err := self.dispatch_char(utils.UTF8State(0xfffd))
				if err != nil {
					return err
				}
			}
		}
	default:
		err := self.dispatch_byte(b)
		if err != nil {
			self.reset_state()
			return err
		}
	}
	return nil
}

func (self *EscapeCodeParser) Parse(data []byte) error {
	for _, b := range data {
		err := self.ParseByte(b)
		if err != nil {
			return err
		}
	}
	return nil
}

func (self *EscapeCodeParser) Reset() {
	self.reset_state()
}

func (self *EscapeCodeParser) write_ch(ch byte) {
	self.current_buffer = append(self.current_buffer, ch)
}

func csi_type(ch byte) csi_char_type {
	if (0x30 <= ch && ch <= 0x3f) || ch == '-' {
		return parameter_csi_char
	}
	if 0x40 <= ch && ch <= 0x7E {
		return final_csi_char
	}
	if 0x20 <= ch && ch <= 0x2F {
		return intermediate_csi_char
	}
	return unknown_csi_char
}

func (self *EscapeCodeParser) reset_state() {
	self.current_buffer = self.current_buffer[:0]
	self.bracketed_paste_buffer = self.bracketed_paste_buffer[:0]
	self.state = normal
	self.utf8_state = utils.UTF8_ACCEPT
	self.utf8_codep = utils.UTF8_ACCEPT
	self.current_callback = nil
	self.csi_state = parameter
}

func (self *EscapeCodeParser) dispatch_esc_code() error {
	if self.state == csi && bytes.Equal(self.current_buffer, bracketed_paste_start) {
		self.reset_state()
		self.state = bracketed_paste
		return nil
	}
	var err error
	if self.current_callback != nil {
		err = self.current_callback(self.current_buffer)
	}
	self.reset_state()
	return err
}

func (self *EscapeCodeParser) invalid_escape_code() {
	self.reset_state()
}

func (self *EscapeCodeParser) dispatch_rune(ch utils.UTF8State) error {
	if self.HandleRune != nil {
		return self.HandleRune(rune(ch))
	}
	return nil
}

func (self *EscapeCodeParser) bp_buffer_equals(chars []utils.UTF8State) bool {
	if len(self.bracketed_paste_buffer) != len(chars) {
		return false
	}
	for i, q := range chars {
		if self.bracketed_paste_buffer[i] != q {
			return false
		}
	}
	return true
}

func (self *EscapeCodeParser) dispatch_char(ch utils.UTF8State) error {
	if self.state == bracketed_paste {
		dispatch := func() error {
			if len(self.bracketed_paste_buffer) > 0 {
				for _, c := range self.bracketed_paste_buffer {
					err := self.dispatch_rune(c)
					if err != nil {
						return err
					}
				}
				self.bracketed_paste_buffer = self.bracketed_paste_buffer[:0]
			}
			return self.dispatch_rune(ch)
		}
		handle_ch := func(chars ...utils.UTF8State) error {
			if self.bp_buffer_equals(chars) {
				self.bracketed_paste_buffer = append(self.bracketed_paste_buffer, ch)
				if self.bracketed_paste_buffer[len(self.bracketed_paste_buffer)-1] == '~' {
					self.reset_state()
					if self.HandleEndOfBracketedPaste != nil {
						if err := self.HandleEndOfBracketedPaste(); err != nil {
							return err
						}
					}
				}
				return nil
			} else {
				return dispatch()
			}
		}
		switch ch {
		case 0x1b:
			return handle_ch()
		case '[':
			return handle_ch(0x1b)
		case '2':
			return handle_ch(0x1b, '[')
		case '0':
			return handle_ch(0x1b, '[', '2')
		case '1':
			return handle_ch(0x1b, '[', '2', '0')
		case '~':
			return handle_ch(0x1b, '[', '2', '0', '1')
		default:
			return dispatch()
		}
	} // end self.state == bracketed_paste

	switch ch {
	case 0x1b:
		self.state = esc
	case 0x90:
		self.state = st
		self.current_callback = self.HandleDCS
	case 0x9b:
		self.state = csi
		self.current_callback = self.HandleCSI
	case 0x9d:
		self.state = st_or_bel
		self.current_callback = self.HandleOSC
	case 0x98:
		self.state = st
		self.current_callback = self.HandleSOS
	case 0x9e:
		self.state = st
		self.current_callback = self.HandlePM
	case 0x9f:
		self.state = st
		self.current_callback = self.HandleAPC
	default:
		return self.dispatch_rune(ch)
	}
	return nil
}

func (self *EscapeCodeParser) dispatch_byte(ch byte) error {
	switch self.state {
	case esc:
		switch ch {
		case 'P':
			self.state = st
			self.current_callback = self.HandleDCS
		case '[':
			self.state = csi
			self.csi_state = parameter
			self.current_callback = self.HandleCSI
		case ']':
			self.state = st_or_bel
			self.current_callback = self.HandleOSC
		case '^':
			self.state = st
			self.current_callback = self.HandlePM
		case '_':
			self.state = st
			self.current_callback = self.HandleAPC
		case 'D', 'E', 'H', 'M', 'N', 'O', 'Z', '6', '7', '8', '9', '=', '>', 'F', 'c', 'l', 'm', 'n', 'o', '|', '}', '~':
		default:
			// we drop this dangling Esc and reparse the byte after the esc
			self.reset_state()
			return self.ParseByte(ch)
		}
	case csi:
		self.write_ch(ch)
		switch self.csi_state {
		case parameter:
			switch csi_type(ch) {
			case intermediate_csi_char:
				self.csi_state = intermediate
			case final_csi_char:
				return self.dispatch_esc_code()
			case unknown_csi_char:
				self.invalid_escape_code()
			}
		case intermediate:
			switch csi_type(ch) {
			case parameter_csi_char, unknown_csi_char:
				self.invalid_escape_code()
			case final_csi_char:
				return self.dispatch_esc_code()
			}
		}
	case st_or_bel:
		if ch == 0x7 {
			return self.dispatch_esc_code()
		}
		fallthrough
	case st:
		if ch == 0x1b {
			self.state = esc_st
		} else if ch == 0xc2 {
			self.state = c1_st
		} else {
			self.write_ch(ch)
		}
	case esc_st:
		if ch == '\\' {
			return self.dispatch_esc_code()
		} else {
			self.state = st
			self.write_ch(0x1b)
			if ch != 0x1b {
				self.write_ch(ch)
			}
		}
	case c1_st:
		if ch == 0x9c {
			return self.dispatch_esc_code()
		} else {
			self.state = st
			self.write_ch(0xc2)
			self.write_ch(ch)
		}
	}
	return nil
}
