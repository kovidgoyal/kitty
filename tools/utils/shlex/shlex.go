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

To access the raw token stream (which includes tokens for spaces):

	  t := NewTokenizer(os.Stdin)
	  for ; token, err := t.Next(); err != nil {
		// process token
	  }
*/
package shlex

// Based on https://pkg.go.dev/github.com/google/shlex with many improvements
// Relicensed to GPLv3 since all my additions.changes are GPLv3 which makes the
// original work with was APL2 also GPLv3

import (
	"errors"
	"fmt"
	"io"
	"strings"
)

// TokenType is a top-level token classification: A word, space, unknown.
type TokenType int

// runeTokenClass is the type of a UTF-8 character classification: A quote, space, escape.
type runeTokenClass int

// the internal state used by the lexer state machine
type lexerState int

// Token is a (type, value) pair representing a lexographical token.
type Token struct {
	Type  TokenType
	Value string
	Pos   int64
}

// Named classes of UTF-8 runes
const (
	spaceRunes            = " \t\r\n"
	escapingQuoteRunes    = `"`
	nonEscapingQuoteRunes = "'"
	escapeRunes           = `\`
)

// Classes of rune token
const (
	unknownRuneClass runeTokenClass = iota
	spaceRuneClass
	escapingQuoteRuneClass
	nonEscapingQuoteRuneClass
	escapeRuneClass
	eofRuneClass
)

// Classes of lexographic token
const (
	UnknownToken TokenType = iota
	WordToken
	SpaceToken
)

func (t TokenType) String() string {
	switch t {
	default:
		return "UnknownToken"
	case WordToken:
		return "WordToken"
	case SpaceToken:
		return "SpaceToken"
	}
}

// Lexer state machine states
const (
	startState           lexerState = iota // no runes have been seen
	inWordState                            // processing regular runes in a word
	inSpaceState                           // processing runes in a space
	escapingState                          // we have just consumed an escape rune; the next rune is literal
	escapingQuotedState                    // we have just consumed an escape rune within a quoted string
	quotingEscapingState                   // we are within a quoted string that supports escaping ("...")
	quotingState                           // we are within a string that does not support escaping ('...')
)

// tokenClassifier is used for classifying rune characters.
type tokenClassifier map[rune]runeTokenClass

func (typeMap tokenClassifier) addRuneClass(runes string, tokenType runeTokenClass) {
	for _, runeChar := range runes {
		typeMap[runeChar] = tokenType
	}
}

// newDefaultClassifier creates a new classifier for ASCII characters.
func newDefaultClassifier() tokenClassifier {
	t := tokenClassifier{}
	t.addRuneClass(spaceRunes, spaceRuneClass)
	t.addRuneClass(escapingQuoteRunes, escapingQuoteRuneClass)
	t.addRuneClass(nonEscapingQuoteRunes, nonEscapingQuoteRuneClass)
	t.addRuneClass(escapeRunes, escapeRuneClass)
	return t
}

// ClassifyRune classifiees a rune
func (t tokenClassifier) ClassifyRune(runeVal rune) runeTokenClass {
	return t[runeVal]
}

// Lexer turns an input stream into a sequence of tokens. Whitespace is skipped.
type Lexer Tokenizer

// NewLexer creates a new lexer from an input stream.
func NewLexer(x io.RuneReader) *Lexer {

	return (*Lexer)(NewTokenizer(x))
}

// Next returns the next word, or an error. If there are no more words,
// the error will be io.EOF.
func (l *Lexer) Next() (string, error) {
	for {
		token, err := (*Tokenizer)(l).Next()
		if err != nil {
			return "", err
		}
		switch token.Type {
		case WordToken:
			return token.Value, nil
		case SpaceToken:
			// skip spaces
		default:
			return "", fmt.Errorf("Unknown token type: %s", token.Type)
		}
	}
}

// Tokenizer turns an input stream into a sequence of typed tokens
type Tokenizer struct {
	input      io.RuneReader
	classifier tokenClassifier
	pos        int64
	redo_rune  struct {
		char      rune
		sz        int
		rune_type runeTokenClass
	}
}

// NewTokenizer creates a new tokenizer from an input stream.
func NewTokenizer(input io.RuneReader) *Tokenizer {
	classifier := newDefaultClassifier()
	return &Tokenizer{
		input:      input,
		classifier: classifier}
}

var ErrTrailingEscape error = errors.New("EOF found after escape character")
var ErrTrailingQuoteEscape error = errors.New("EOF found after escape character for double quote")
var ErrUnclosedDoubleQuote error = errors.New("EOF found when expecting closing double quote")
var ErrUnclosedSingleQuote error = errors.New("EOF found when expecting closing single quote")

// scanStream scans the stream for the next token using the internal state machine.
// It will panic if it encounters a rune which it does not know how to handle.
func (t *Tokenizer) scanStream() (*Token, error) {
	state := startState
	var tokenType TokenType
	var nextRune rune
	var nextRuneType runeTokenClass
	var err error
	var sz int
	value := strings.Builder{}
	pos_at_start := t.pos

	unread_rune := func() {
		t.redo_rune.sz = sz
		t.redo_rune.char = nextRune
		t.redo_rune.rune_type = nextRuneType
		t.pos -= int64(sz)
	}

	token := func() *Token {
		return &Token{tokenType, value.String(), pos_at_start}
	}

	for {
		if t.redo_rune.sz > 0 {
			nextRune, sz = t.redo_rune.char, t.redo_rune.sz
			nextRuneType = t.redo_rune.rune_type
			t.redo_rune.sz = 0
		} else {
			nextRune, sz, err = t.input.ReadRune()
			nextRuneType = t.classifier.ClassifyRune(nextRune)
		}

		if err == io.EOF {
			nextRuneType = eofRuneClass
			err = nil
		} else if err != nil {
			return nil, err
		}
		t.pos += int64(sz)

		switch state {
		case startState: // no runes read yet
			{
				switch nextRuneType {
				case eofRuneClass:
					{
						return nil, io.EOF
					}
				case spaceRuneClass:
					{
						tokenType = SpaceToken
						value.WriteRune(nextRune)
						state = inSpaceState
					}
				case escapingQuoteRuneClass:
					{
						tokenType = WordToken
						state = quotingEscapingState
					}
				case nonEscapingQuoteRuneClass:
					{
						tokenType = WordToken
						state = quotingState
					}
				case escapeRuneClass:
					{
						tokenType = WordToken
						state = escapingState
					}
				default:
					{
						tokenType = WordToken
						value.WriteRune(nextRune)
						state = inWordState
					}
				}
			}
		case inSpaceState: // in a sequence of spaces separating words
			{
				switch nextRuneType {
				case spaceRuneClass:
					{
						value.WriteRune(nextRune)
					}
				default:
					{
						unread_rune()
						return token(), err
					}
				}
			}
		case inWordState: // in a regular word
			{
				switch nextRuneType {
				case eofRuneClass:
					{
						return token(), err
					}
				case spaceRuneClass:
					{
						unread_rune()
						return token(), err
					}
				case escapingQuoteRuneClass:
					{
						state = quotingEscapingState
					}
				case nonEscapingQuoteRuneClass:
					{
						state = quotingState
					}
				case escapeRuneClass:
					{
						state = escapingState
					}
				default:
					{
						value.WriteRune(nextRune)
					}
				}
			}
		case escapingState: // the rune after an escape character
			{
				switch nextRuneType {
				case eofRuneClass:
					{
						err = ErrTrailingEscape
						return token(), err
					}
				default:
					{
						state = inWordState
						value.WriteRune(nextRune)
					}
				}
			}
		case escapingQuotedState: // the next rune after an escape character, in double quotes
			{
				switch nextRuneType {
				case eofRuneClass:
					{
						err = ErrTrailingQuoteEscape
						return token(), err
					}
				default:
					{
						state = quotingEscapingState
						value.WriteRune(nextRune)
					}
				}
			}
		case quotingEscapingState: // in escaping double quotes
			{
				switch nextRuneType {
				case eofRuneClass:
					{
						err = ErrUnclosedDoubleQuote
						return token(), err
					}
				case escapingQuoteRuneClass:
					{
						state = inWordState
					}
				case escapeRuneClass:
					{
						state = escapingQuotedState
					}
				default:
					{
						value.WriteRune(nextRune)
					}
				}
			}
		case quotingState: // in non-escaping single quotes
			{
				switch nextRuneType {
				case eofRuneClass:
					{
						err = ErrUnclosedSingleQuote
						return token(), err
					}
				case nonEscapingQuoteRuneClass:
					{
						state = inWordState
					}
				default:
					{
						value.WriteRune(nextRune)
					}
				}
			}
		default:
			{
				return nil, fmt.Errorf("Unexpected state: %v", state)
			}
		}
	}
}

// Next returns the next token in the stream.
func (t *Tokenizer) Next() (*Token, error) {
	return t.scanStream()
}

// Pos returns the current position in the string as a byte offset
func (t *Tokenizer) Pos() int64 {
	return t.pos
}

// Split partitions a string into a slice of strings.
func Split(s string) ([]string, error) {
	l := NewLexer(strings.NewReader(s))
	subStrings := make([]string, 0)
	for {
		word, err := l.Next()
		if err != nil {
			if err == io.EOF {
				return subStrings, nil
			}
			return subStrings, err
		}
		subStrings = append(subStrings, word)
	}
}

// SplitForCompletion partitions a string into a slice of strings. It differs from Split in being
// more relaxed about errors and also adding an empty string at the end if s ends with a SpaceToken.
func SplitForCompletion(s string) (argv []string, position_of_last_arg int) {
	t := NewTokenizer(strings.NewReader(s))
	argv = make([]string, 0, len(s)/4)
	token := &Token{}
	for {
		ntoken, err := t.Next()
		if err == io.EOF {
			if token.Type == SpaceToken {
				argv = append(argv, "")
				token.Pos += int64(len(token.Value))
			}
			return argv, int(token.Pos)
		}
		if ntoken == nil {
			return []string{}, -1
		}
		switch ntoken.Type {
		case WordToken:
			argv = append(argv, ntoken.Value)
		case SpaceToken:
			// skip spaces
		default:
			return []string{}, -1
		}
		token = ntoken
	}
}
