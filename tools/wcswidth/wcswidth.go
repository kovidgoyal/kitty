package wcswidth

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
}

func CreateWCWidthIterator() *WCWidthIterator {
	var ans WCWidthIterator
	ans.parser.HandleRune = ans.handle_rune
	return &ans
}

func (self *WCWidthIterator) Reset() {
	self.prev_ch = 0
	self.prev_width = 0
	self.current_width = 0
	self.parser.Reset()
}

func (self *WCWidthIterator) handle_rune(ch rune) error {
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

func (self *WCWidthIterator) Parse(b []byte) (ans int) {
	self.current_width = 0
	self.parser.Parse(b)
	return self.current_width
}

func Stringwidth(text string) int {
	w := CreateWCWidthIterator()
	return w.Parse([]byte(text))
}
