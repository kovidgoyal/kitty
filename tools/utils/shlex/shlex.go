/*
Package shlex implements a simple lexer which splits input in to tokens using
shell-style rules for quoting.

The basic use case uses the default ASCII lexer to split a string into sub-strings:

	shlex.Split("one \"two three\" four") -> []string{"one", "two three", "four"}

To process a stream of strings:

	l := NewLexer(os.Stdin)
	for ; token, err := l.Next(); err != nil {
		// process token
	}
*/
package shlex

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/utils"
	"strings"
	"unicode/utf8"
)

type Word struct {
	Value   string // The word is empty if EOF is reached
	Pos     int    // The position in the input string of the word or the trailer
	Err     error  // Indicates an error (unterminated string or trailing unescaped backslash)
	Trailer string // Extra trailing data such as an unterminated string or an unescaped backslash. Present only if Err != nil
}

type lexer_state int

// Lexer state machine states
const (
	lex_normal lexer_state = iota
	word
	string_without_escapes
	string_with_escapes
)

// Lexer turns an input stream into a sequence of tokens. Whitespace is skipped.
type Lexer struct {
	state                       lexer_state
	src                         string
	src_sz, src_pos, word_start int
	buf                         strings.Builder
}

// NewLexer creates a new lexer from an input string.
func NewLexer(x string) *Lexer {
	return &Lexer{src: x, src_sz: len(x)}
}

func (self *Lexer) start_word() {
	self.buf.Reset()
	self.word_start = self.src_pos - 1
}

func (self *Lexer) get_word() Word {
	return Word{Pos: self.word_start, Value: self.buf.String()}
}

func (self *Lexer) write_ch(ch byte) {
	self.buf.WriteByte(ch)
}

func (self *Lexer) write_escaped_ch() bool {
	ch, count := utf8.DecodeRuneInString(self.src[self.src_pos:])
	if count > 0 {
		self.src_pos += count
		if ch != utf8.RuneError {
			self.buf.WriteRune(ch)
		}
		return true
	}
	return false
}

// Next returns the next word. At EOF Word.Value will be ""
func (self *Lexer) Next() (ans Word) {
	const string_with_escapes_delim = '"'
	const string_without_escapes_delim = '\''
	const escape_char = '\\'
	for self.src_pos < self.src_sz {
		ch := self.src[self.src_pos]
		self.src_pos++
		switch self.state {
		case lex_normal:
			switch ch {
			case ' ', '\n', '\r', '\t':
			case string_with_escapes_delim:
				self.state = string_with_escapes
				self.start_word()
			case string_without_escapes_delim:
				self.state = string_without_escapes
				self.start_word()
			case escape_char:
				self.start_word()
				if !self.write_escaped_ch() {
					ans.Trailer = "\\"
					ans.Err = fmt.Errorf("Extra backslash at end of input")
					ans.Pos = self.word_start
					return
				}
				self.state = word
			default:
				self.state = word
				self.start_word()
				self.write_ch(ch)
			}
		case word:
			switch ch {
			case ' ', '\n', '\r', '\t':
				self.state = lex_normal
				if self.buf.Len() > 0 {
					return self.get_word()
				}
			case string_with_escapes_delim:
				self.state = string_with_escapes
			case string_without_escapes_delim:
				self.state = string_without_escapes
			case escape_char:
				if !self.write_escaped_ch() {
					ans.Pos = self.word_start
					ans.Trailer = self.buf.String() + "\\"
					ans.Err = fmt.Errorf("Extra backslash at end of input")
					return
				}
			default:
				self.write_ch(ch)
			}
		case string_without_escapes:
			switch ch {
			case string_without_escapes_delim:
				self.state = word
			default:
				self.write_ch(ch)
			}
		case string_with_escapes:
			switch ch {
			case string_with_escapes_delim:
				self.state = word
			case escape_char:
				self.write_escaped_ch()
			default:
				self.write_ch(ch)
			}
		}
	}
	switch self.state {
	case word:
		self.state = lex_normal
		if self.buf.Len() > 0 {
			return self.get_word()
		}
	case string_with_escapes, string_without_escapes:
		self.state = lex_normal
		ans.Trailer = self.buf.String()
		ans.Pos = self.word_start
		ans.Err = fmt.Errorf("Unterminated string at end of input")
		return
	case lex_normal:

	}
	return
}

// Split partitions a string into a slice of strings.
func Split(s string) (ans []string, err error) {
	l := NewLexer(s)
	var word Word
	for {
		word = l.Next()
		if word.Err != nil {
			return ans, word.Err
		}
		if word.Value == "" {
			break
		}
		ans = append(ans, word.Value)
	}
	return
}

func Quote(s string) string {
	if s == "" {
		return s
	}
	if utils.MustCompile(`[^\w@%+=:,./-]`).MatchString(s) {
		return "'" + strings.ReplaceAll(s, "'", "'\"'\"'") + "'"
	}
	return s
}

// SplitForCompletion partitions a string into a slice of strings. It differs from Split in being
// more relaxed about errors and also adding an empty string at the end if s ends with a Space.
func SplitForCompletion(s string) (argv []string, position_of_last_arg int) {
	t := NewLexer(s)
	argv = make([]string, 0, len(s)/4)
	for {
		word := t.Next()
		if word.Value == "" {
			if word.Trailer == "" {
				trimmed := strings.TrimRight(s, " ")
				if len(trimmed) < len(s) { // trailing spaces
					pos := position_of_last_arg
					if len(argv) > 0 {
						pos += len(argv[len(argv)-1])
					}
					if pos < len(s) { // trailing whitespace
						argv = append(argv, "")
						position_of_last_arg += len(s) - pos + 1
					}
				}
			} else {
				argv = append(argv, word.Trailer)
				position_of_last_arg = word.Pos
			}
			break
		}
		position_of_last_arg = word.Pos
		argv = append(argv, word.Value)
	}
	return
}
