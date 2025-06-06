package fzf

import (
	"fmt"
	"os"
	"strings"
	"sync"
	"unicode"
	"unicode/utf8"
	"unsafe"

	"github.com/kovidgoyal/kitty/tools/utils"
	"golang.org/x/text/unicode/norm"
)

var _ = fmt.Print

type Chars struct {
	bytes []byte
	runes []rune
}

func check_ascii(bytes []byte) (ascii_until int) {
	slen := len(bytes)
	// Process 8 bytes at a time
	i := 0
	for ; i+8 <= slen; i += 8 {
		v := *(*uint64)(unsafe.Pointer(&bytes[i]))
		// If any byte has its high bit set, v & 0x8080808080808080 != 0
		if v&0x8080808080808080 != 0 {
			// At least one non-ASCII byte in this chunk, find which
			for j := range 8 {
				if bytes[i+j]&utf8.RuneSelf != 0 {
					return i + j
				}
			}
		}
	}
	// Handle remaining bytes
	for ; i < slen; i++ {
		if bytes[i]&utf8.RuneSelf != 0 {
			return i
		}
	}
	return -1
}

func CharsFromString(text string) (ans Chars) {
	ans.bytes = utils.UnsafeStringToBytes(text)
	ascii_until := check_ascii(ans.bytes)
	if ascii_until > -1 {
		runes := []rune(norm.NFC.String(text[ascii_until:]))
		ans.runes = make([]rune, ascii_until+len(runes))
		for i := range ascii_until {
			ans.runes[i] = rune(ans.bytes[i])
		}
		copy(ans.runes[ascii_until:], runes)
	}
	return
}

func CharsFromStringWithoutAccents(text string) (ans Chars) {
	ans.bytes = utils.UnsafeStringToBytes(text)
	ascii_until := check_ascii(ans.bytes)
	if ascii_until > -1 {
		runes := []rune(norm.NFD.String(text[ascii_until:]))
		ans.runes = make([]rune, ascii_until, ascii_until+len(runes))
		for i := range ascii_until {
			ans.runes[i] = rune(ans.bytes[i])
		}
		for _, r := range runes {
			if !unicode.Is(unicode.Mn, r) {
				ans.runes = append(ans.runes, r)
			}
		}
	}
	return
}

func (c *Chars) Bytes() []byte  { return c.bytes }
func (c *Chars) Is_ASCII() bool { return c.runes == nil }
func (c *Chars) Get(i int) rune {
	if c.runes != nil {
		return c.runes[i]
	}
	return rune(c.bytes[i])
}
func (c *Chars) Length() int {
	if c.runes != nil {
		return len(c.runes)
	}
	return len(c.bytes)
}

func (c *Chars) CopyRunes(dest []rune, from int) {
	if c.runes != nil {
		copy(dest, c.runes[from:])
		return
	}
	for idx, b := range c.bytes[from:][:len(dest)] {
		dest[idx] = rune(b)
	}
}

type charClass int

const (
	charWhite charClass = iota
	charNonWord
	charDelimiter
	charLower
	charUpper
	charLetter
	charNumber
)

const (
	scoreMatch        = 16
	scoreGapStart     = -3
	scoreGapExtension = -1

	// We prefer matches at the beginning of a word, but the bonus should not be
	// too great to prevent the longer acronym matches from always winning over
	// shorter fuzzy matches. The bonus point here was specifically chosen that
	// the bonus is cancelled when the gap between the acronyms grows over
	// 8 characters, which is approximately the average length of the words found
	// in web2 dictionary and my file system.
	bonusBoundary = scoreMatch / 2

	// Although bonus point for non-word characters is non-contextual, we need it
	// for computing bonus points for consecutive chunks starting with a non-word
	// character.
	bonusNonWord = scoreMatch / 2

	// Edge-triggered bonus for matches in camelCase words.
	// Compared to word-boundary case, they don't accompany single-character gaps
	// (e.g. FooBar vs. foo-bar), so we deduct bonus point accordingly.
	bonusCamel123 = bonusBoundary + scoreGapExtension

	// Minimum bonus point given to characters in consecutive chunks.
	// Note that bonus points for consecutive matches shouldn't have needed if we
	// used fixed match score as in the original algorithm.
	bonusConsecutive = -(scoreGapStart + scoreGapExtension)

	// The first character in the typed pattern usually has more significance
	// than the rest so it's important that it appears at special positions where
	// bonus points are given, e.g. "to-go" vs. "ongoing" on "og" or on "ogo".
	// The amount of the extra bonus should be limited so that the gap penalty is
	// still respected.
	bonusFirstCharMultiplier = 2
)

const whiteChars = " \t\n\v\f\r\x85\xA0"

type Result struct {
	Score     uint // A value of zero means did not match
	Positions []int
}

type FuzzyMatcher struct {
	Case_sensitive, Ignore_accents, Backwards, Without_positions bool

	// Extra bonus for word boundary after whitespace character or beginning of the string
	bonusBoundaryWhite int16

	// Extra bonus for word boundary after slash, colon, semi-colon, and comma
	bonusBoundaryDelimiter int16

	initialCharClass charClass

	// A minor optimization that can give 15%+ performance boost
	asciiCharClasses [unicode.MaxASCII + 1]charClass

	// A minor optimization that can give yet another 5% performance boost
	bonusMatrix [charNumber + 1][charNumber + 1]int16

	delimiterChars string

	cache       map[string]Result
	cache_mutex sync.Mutex
}

func (m *FuzzyMatcher) bonusFor(prevClass charClass, class charClass) int16 {
	if class > charNonWord {
		switch prevClass {
		case charWhite:
			// Word boundary after whitespace
			return m.bonusBoundaryWhite
		case charDelimiter:
			// Word boundary after a delimiter character
			return m.bonusBoundaryDelimiter
		case charNonWord:
			// Word boundary
			return bonusBoundary
		}
	}

	if prevClass == charLower && class == charUpper ||
		prevClass != charNumber && class == charNumber {
		// camelCase letter123
		return bonusCamel123
	}

	switch class {
	case charNonWord, charDelimiter:
		return bonusNonWord
	case charWhite:
		return m.bonusBoundaryWhite
	}
	return 0
}

type Scheme string

const (
	DEFAULT_SCHEME Scheme = "default"
	PATH_SCHEME    Scheme = "path"
	HISTORY_SCHEME Scheme = "history"
)

func new_fuzzy_matcher(scheme Scheme) (ans *FuzzyMatcher) {
	ans = &FuzzyMatcher{
		bonusBoundaryWhite:     bonusBoundary + 2,
		bonusBoundaryDelimiter: bonusBoundary + 1,
		delimiterChars:         "/,:;|",
		cache:                  make(map[string]Result),
	}
	switch scheme {
	case PATH_SCHEME:
		ans.bonusBoundaryWhite = bonusBoundary
		ans.initialCharClass = charDelimiter
		if os.PathSeparator == '/' {
			ans.delimiterChars = "/"
		} else {
			ans.delimiterChars = "/" + string(os.PathSeparator)
		}
	case HISTORY_SCHEME:
		ans.bonusBoundaryWhite = bonusBoundary
		ans.bonusBoundaryDelimiter = bonusBoundary
	}
	for i := 0; i <= unicode.MaxASCII; i++ {
		char := rune(i)
		c := charNonWord
		if char >= 'a' && char <= 'z' {
			c = charLower
		} else if char >= 'A' && char <= 'Z' {
			c = charUpper
		} else if char >= '0' && char <= '9' {
			c = charNumber
		} else if strings.ContainsRune(whiteChars, char) {
			c = charWhite
		} else if strings.ContainsRune(ans.delimiterChars, char) {
			c = charDelimiter
		}
		ans.asciiCharClasses[i] = c
	}
	for i := 0; i <= int(charNumber); i++ {
		for j := 0; j <= int(charNumber); j++ {
			ans.bonusMatrix[i][j] = ans.bonusFor(charClass(i), charClass(j))
		}
	}
	return
}

type slab struct {
	i16                []int16
	i32                []int32
	i16_used, i32_used int
}

const slab_initial_size = 8192

func (s *slab) reset() {
	if s.i16 == nil {
		s.i16 = make([]int16, slab_initial_size)
	}
	if s.i32 == nil {
		s.i32 = make([]int32, slab_initial_size)
	}
	s.i16_used, s.i32_used = 0, 0
}

func (s *slab) alloc16(sz int) []int16 {
	if sz+s.i16_used < len(s.i16) {
		s.i16 = make([]int16, max(slab_initial_size, 2*(s.i16_used+sz)))
		s.i16_used = 0
	}
	pos := s.i16_used
	s.i16_used += sz
	return s.i16[pos:s.i16_used]
}

func (s *slab) alloc32(sz int) []int32 {
	if sz+s.i32_used < len(s.i32) {
		s.i32 = make([]int32, max(slab_initial_size, 2*(s.i32_used+sz)))
		s.i32_used = 0
	}
	pos := s.i32_used
	s.i32_used += sz
	return s.i32[pos:s.i32_used]
}
