package utils

import (
	"bytes"
	"fmt"
)

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
	utf8_state             UTF8State
	csi_state              csi_state
	current_buffer         []byte
	bracketed_paste_buffer []UTF8State
	current_callback       func([]byte)

	// Whether to send escape code bytes as soon as they are received or to
	// buffer and send full escape codes
	streaming bool

	// Callbacks
	HandleRune func(rune)
	HandleCSI  func([]byte)
	HandleOSC  func([]byte)
	HandleDCS  func([]byte)
	HandlePM   func([]byte)
	HandleSOS  func([]byte)
	HandleAPC  func([]byte)
}

func (self *EscapeCodeParser) SetStreaming(streaming bool) error {
	if self.state != normal || len(self.current_buffer) > 0 {
		return fmt.Errorf("Cannot change streaming state when not in reset state")
	}
	self.streaming = streaming
	return nil
}

func (self *EscapeCodeParser) IsStreaming() bool {
	return self.streaming
}

func (self *EscapeCodeParser) Parse(data []byte) {
	prev := UTF8_ACCEPT
	codep := UTF8_ACCEPT
	for i := 0; i < len(data); i++ {
		switch self.state {
		case normal, bracketed_paste:
			switch decode_utf8(&self.utf8_state, &codep, data[i]) {
			case UTF8_ACCEPT:
				self.dispatch_char(codep)
			case UTF8_REJECT:
				self.utf8_state = UTF8_ACCEPT
				if prev != UTF8_ACCEPT && i > 0 {
					i = i - 1
				}
			}
			prev = self.utf8_state
		default:
			self.dispatch_byte(data[i])
		}
	}
}

func (self *EscapeCodeParser) Reset() {
	self.reset_state()
}

func (self *EscapeCodeParser) write_ch(ch byte) {
	if self.streaming {
		if self.current_callback != nil {
			var data [1]byte = [1]byte{ch}
			self.current_callback(data[:])
		}
		if self.state == csi && len(self.current_buffer) < 4 {
			self.current_buffer = append(self.current_buffer, ch)
		}
	} else {
		self.current_buffer = append(self.current_buffer, ch)
	}
}

func csi_type(ch byte) csi_char_type {
	if 0x30 <= ch && ch <= 0x3f {
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
	self.utf8_state = UTF8_ACCEPT
	self.current_callback = nil
	self.csi_state = parameter
}

func (self *EscapeCodeParser) dispatch_esc_code() {
	if self.state == csi && bytes.Equal(self.current_buffer, bracketed_paste_start) {
		self.reset_state()
		self.state = bracketed_paste
		return
	}
	if self.current_callback != nil {
		self.current_callback(self.current_buffer)
	}
	self.reset_state()
}

func (self *EscapeCodeParser) invalid_escape_code() {
	self.reset_state()
}

func (self *EscapeCodeParser) dispatch_rune(ch UTF8State) {
	if self.HandleRune != nil {
		self.HandleRune(rune(ch))
	}
}

func (self *EscapeCodeParser) bp_buffer_equals(chars []UTF8State) bool {
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

func (self *EscapeCodeParser) dispatch_char(ch UTF8State) {
	if self.state == bracketed_paste {
		dispatch := func() {
			if len(self.bracketed_paste_buffer) > 0 {
				for _, c := range self.bracketed_paste_buffer {
					self.dispatch_rune(c)
				}
				self.bracketed_paste_buffer = self.bracketed_paste_buffer[:0]
			}
			self.dispatch_rune(ch)
		}
		handle_ch := func(chars ...UTF8State) {
			if self.bp_buffer_equals(chars) {
				self.bracketed_paste_buffer = append(self.bracketed_paste_buffer, ch)
				if self.bracketed_paste_buffer[len(self.bracketed_paste_buffer)-1] == '~' {
					self.reset_state()
				}
			} else {
				dispatch()
			}
		}
		switch ch {
		case 0x1b:
			handle_ch()
		case '[':
			handle_ch(0x1b)
		case '2':
			handle_ch(0x1b, '[')
		case '0':
			handle_ch(0x1b, '[', '2')
		case '1':
			handle_ch(0x1b, '[', '2', '0')
		case '~':
			handle_ch(0x1b, '[', '2', '0', '1')
		default:
			dispatch()
		}
		return
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
		self.dispatch_rune(ch)
	}
}

func (self *EscapeCodeParser) dispatch_byte(ch byte) {
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
		default:
			self.state = normal
		}
	case csi:
		self.write_ch(ch)
		switch self.csi_state {
		case parameter:
			switch csi_type(ch) {
			case intermediate_csi_char:
				self.csi_state = intermediate
			case final_csi_char:
				self.dispatch_esc_code()
			case unknown_csi_char:
				self.invalid_escape_code()
			}
		case intermediate:
			switch csi_type(ch) {
			case parameter_csi_char, unknown_csi_char:
				self.invalid_escape_code()
			case final_csi_char:
				self.dispatch_esc_code()
			}
		}
	case st_or_bel:
		if ch == 0x7 {
			self.dispatch_esc_code()
			return
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
			self.dispatch_esc_code()
		} else {
			self.state = st
			self.write_ch(0x1b)
			if ch != 0x1b {
				self.write_ch(ch)
			}
		}
	case c1_st:
		if ch == 0x9c {
			self.dispatch_esc_code()
		} else {
			self.state = st
			self.write_ch(0xc2)
			self.write_ch(ch)
		}
	}
}
