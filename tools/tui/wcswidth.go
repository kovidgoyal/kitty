package tui

func IsFlagCodepoint(ch rune) bool {
	return 0x1F1E6 <= ch && ch <= 0x1F1FF
}

func IsFlagPair(a rune, b rune) bool {
	return IsFlagCodepoint(a) && IsFlagCodepoint(b)
}

type parser_state uint8

type WCWidthIterator struct {
	prev_ch    rune
	prev_width int
	state      parser_state
}

func (self *WCWidthIterator) Reset() {
	self.prev_ch = 0
	self.prev_width = 0
	self.state = 0
}

func (self *WCWidthIterator) Step(ch rune) int {
	var ans int = 0
	const (
		normal            parser_state = 0
		in_esc            parser_state = 1
		in_csi            parser_state = 2
		flag_pair_started parser_state = 3
		in_st_terminated  parser_state = 4
	)
	switch self.state {
	case in_csi:
		self.prev_width = 0
		if 0x40 <= ch && ch <= 0x7e {
			self.state = normal
		}
	case in_st_terminated:
		self.prev_width = 0
		if ch == 0x9c || (ch == '\\' && self.prev_ch == 0x1b) {
			self.state = normal
		}
	case flag_pair_started:
		self.state = normal
		if IsFlagPair(self.prev_ch, ch) {
			break
		}
		fallthrough
	case normal:
		switch ch {
		case 0x1b:
			self.prev_width = 0
			self.state = in_esc
		case 0xfe0f:
			if IsEmojiPresentationBase(self.prev_ch) && self.prev_width == 1 {
				ans += 1
				self.prev_width = 2
			} else {
				self.prev_width = 0
			}
		case 0xfe0e:
			if IsEmojiPresentationBase(self.prev_ch) && self.prev_width == 2 {
				ans -= 1
				self.prev_width = 1
			} else {
				self.prev_width = 0
			}
		default:
			if IsFlagCodepoint(ch) {
				self.state = flag_pair_started
			}
			w := Wcwidth(ch)
			switch w {
			case -1:
			case 0:
				self.prev_width = 0
			case 2:
				self.prev_width = 2
			default:
				self.prev_width = 1
			}
			ans += self.prev_width
		}

	case in_esc:
		switch ch {
		case '[':
			self.state = in_csi
		case 'P', ']', 'X', '^', '_':
			self.state = in_st_terminated
		case 'D', 'E', 'H', 'M', 'N', 'O', 'Z', '6', '7', '8', '9', '=', '>', 'F', 'c', 'l', 'm', 'n', 'o', '|', '}', '~':
		default:
			self.prev_ch = 0x1b
			self.prev_width = 0
			self.state = normal
			return self.Step(ch)
		}
	}
	self.prev_ch = ch
	return ans
}

func Wcswidth(text string) int {
	var w WCWidthIterator
	ans := 0
	for _, ch := range []rune(text) {
		ans += w.Step(ch)
	}
	return ans
}
