package fzf

import (
	"bytes"
	"fmt"
	"slices"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/utils"
	"golang.org/x/text/unicode/norm"
)

var _ = fmt.Print

/*

Algorithm
---------

Based on code from fzf (MIT licensed):
https://github.com/junegunn/fzf

FuzzyMatch implements a modified version of Smith-Waterman algorithm to find
the optimal solution (highest score) according to the scoring criteria. Unlike
the original algorithm, omission or mismatch of a character in the pattern is
not allowed.

Scoring criteria
----------------

- We prefer matches at special positions, such as the start of a word, or
  uppercase character in camelCase words.

- That is, we prefer an occurrence of the pattern with more characters
  matching at special positions, even if the total match length is longer.
    e.g. "fuzzyfinder" vs. "fuzzy-finder" on "ff"
                            ````````````
- Also, if the first character in the pattern appears at one of the special
  positions, the bonus point for the position is multiplied by a constant
  as it is extremely likely that the first character in the typed pattern
  has more significance than the rest.
    e.g. "fo-bar" vs. "foob-r" on "br"
          ``````
- But since fzf is still a fuzzy finder, not an acronym finder, we should also
  consider the total length of the matched substring. This is why we have the
  gap penalty. The gap penalty increases as the length of the gap (distance
  between the matching characters) increases, so the effect of the bonus is
  eventually cancelled at some point.
    e.g. "fuzzyfinder" vs. "fuzzy-blurry-finder" on "ff"
          ```````````
- Consequently, it is crucial to find the right balance between the bonus
  and the gap penalty. The parameters were chosen that the bonus is cancelled
  when the gap size increases beyond 8 characters.

- The bonus mechanism can have the undesirable side effect where consecutive
  matches are ranked lower than the ones with gaps.
    e.g. "foobar" vs. "foo-bar" on "foob"
                       ```````
- To correct this anomaly, we also give extra bonus point to each character
  in a consecutive matching chunk.
    e.g. "foobar" vs. "foo-bar" on "foob"
          ``````
- The amount of consecutive bonus is primarily determined by the bonus of the
  first character in the chunk.
    e.g. "foobar" vs. "out-of-bound" on "oob"
                       ````````````
*/

func try_skip(input *Chars, case_sensitive bool, b byte, from int) int {
	byteArray := input.Bytes()[from:]
	idx := bytes.IndexByte(byteArray, b)
	if idx == 0 {
		// Can't skip any further
		return from
	}
	// We may need to search for the uppercase letter again. We don't have to
	// consider normalization as we can be sure that this is an ASCII string.
	if !case_sensitive && b >= 'a' && b <= 'z' {
		if idx > 0 {
			byteArray = byteArray[:idx]
		}
		uidx := bytes.IndexByte(byteArray, b-32)
		if uidx >= 0 {
			idx = uidx
		}
	}
	if idx < 0 {
		return -1
	}
	return from + idx
}

func ascii_fuzzy_index(input *Chars, pattern []rune, pattern_is_ascii bool, case_sensitive bool) (int, int) {
	// Can't determine
	if !input.Is_ASCII() {
		return 0, input.Length()
	}
	// Can't match
	if !pattern_is_ascii {
		return -1, -1
	}

	firstIdx, idx, lastIdx := 0, 0, 0
	var b byte
	for pidx := range len(pattern) {
		b = byte(pattern[pidx])
		idx = try_skip(input, case_sensitive, b, idx)
		if idx < 0 {
			return -1, -1
		}
		if pidx == 0 && idx > 0 {
			// Step back to find the right bonus point
			firstIdx = idx - 1
		}
		lastIdx = idx
		idx++
	}

	// Find the last appearance of the last character of the pattern to limit the search scope
	bu := b
	if !case_sensitive && b >= 'a' && b <= 'z' {
		bu = b - 32
	}
	scope := input.Bytes()[lastIdx:]
	for offset := len(scope) - 1; offset > 0; offset-- {
		if scope[offset] == b || scope[offset] == bu {
			return firstIdx, lastIdx + offset + 1
		}
	}
	return firstIdx, lastIdx + 1
}

func (m *FuzzyMatcher) charClassOfNonAscii(char rune) charClass {
	if unicode.IsLower(char) {
		return charLower
	} else if unicode.IsUpper(char) {
		return charUpper
	} else if unicode.IsNumber(char) {
		return charNumber
	} else if unicode.IsLetter(char) {
		return charLetter
	} else if unicode.IsSpace(char) {
		return charWhite
	} else if strings.ContainsRune(m.delimiterChars, char) {
		return charDelimiter
	}
	return charNonWord
}

// Score the input against pattern. If !m.Case_sensitive pattern must be
// lowercased already. pattern must be non-empty. When m.Ignore_accents
// accents must already be removed from both pattern and input.
func (m *FuzzyMatcher) score_one(input *Chars, pattern []rune, pattern_is_ascii bool, slab *slab) (ans Result) {
	M := len(pattern)
	N := input.Length()
	if M > N {
		return
	}

	// Phase 1. Optimized search for ASCII string
	minIdx, maxIdx := ascii_fuzzy_index(input, pattern, pattern_is_ascii, m.Case_sensitive)
	if minIdx < 0 {
		return
	}
	// fmt.Println(N, maxIdx, idx, maxIdx-idx, input.ToString())
	N = maxIdx - minIdx

	slab.reset()

	H0 := slab.alloc16(N)
	C0 := slab.alloc16(N)
	// Bonus point for each position
	B := slab.alloc16(N)
	// The first occurrence of each character in the pattern
	F := slab.alloc32(M)
	// Rune array
	T := slab.alloc32(N)
	input.CopyRunes(T, minIdx)

	// Phase 2. Calculate bonus for each point
	maxScore, maxScorePos := int16(0), 0
	pidx, lastIdx := 0, 0
	pchar0, pchar, prevH0, prevClass, inGap := pattern[0], pattern[0], int16(0), m.initialCharClass, false
	for off, char := range T {
		var class charClass
		if char <= unicode.MaxASCII {
			class = m.asciiCharClasses[char]
			if !m.Case_sensitive && class == charUpper {
				char += 32
				T[off] = char
			}
		} else {
			class = m.charClassOfNonAscii(char)
			if !m.Case_sensitive && class == charUpper {
				char = unicode.To(unicode.LowerCase, char)
			}
			T[off] = char
		}

		bonus := m.bonusMatrix[prevClass][class]
		B[off] = bonus
		prevClass = class

		if char == pchar {
			if pidx < M {
				F[pidx] = int32(off)
				pidx++
				pchar = pattern[min(pidx, M-1)]
			}
			lastIdx = off
		}

		if char == pchar0 {
			score := scoreMatch + bonus*bonusFirstCharMultiplier
			H0[off] = score
			C0[off] = 1
			if M == 1 && (!m.Backwards && score > maxScore || m.Backwards && score >= maxScore) {
				maxScore, maxScorePos = score, off
				if !m.Backwards && bonus >= bonusBoundary {
					break
				}
			}
			inGap = false
		} else {
			if inGap {
				H0[off] = max(prevH0+scoreGapExtension, 0)
			} else {
				H0[off] = max(prevH0+scoreGapStart, 0)
			}
			C0[off] = 0
			inGap = true
		}
		prevH0 = H0[off]
	}
	if pidx != M {
		return
	}
	if M == 1 {
		if m.Without_positions {
			return Result{Score: uint(maxScore)}
		}
		return Result{Score: uint(maxScore), Positions: []int{minIdx + maxScorePos}}
	}

	// Phase 3. Fill in score matrix (H)
	// Unlike the original algorithm, we do not allow omission.
	f0 := int(F[0])
	width := lastIdx - f0 + 1
	H := slab.alloc16(width * M)
	copy(H, H0[f0:lastIdx+1])

	// Possible length of consecutive chunk at each position.
	C := slab.alloc16(width * M)
	copy(C, C0[f0:lastIdx+1])

	Fsub := F[1:]
	Psub := pattern[1:][:len(Fsub)]
	for off, f := range Fsub {
		f := int(f)
		pchar := Psub[off]
		pidx := off + 1
		row := pidx * width
		inGap := false
		Tsub := T[f : lastIdx+1]
		Bsub := B[f:][:len(Tsub)]
		Csub := C[row+f-f0:][:len(Tsub)]
		Cdiag := C[row+f-f0-1-width:][:len(Tsub)]
		Hsub := H[row+f-f0:][:len(Tsub)]
		Hdiag := H[row+f-f0-1-width:][:len(Tsub)]
		Hleft := H[row+f-f0-1:][:len(Tsub)]
		Hleft[0] = 0
		for off, char := range Tsub {
			col := off + f
			var s1, s2, consecutive int16

			if inGap {
				s2 = Hleft[off] + scoreGapExtension
			} else {
				s2 = Hleft[off] + scoreGapStart
			}

			if pchar == char {
				s1 = Hdiag[off] + scoreMatch
				b := Bsub[off]
				consecutive = Cdiag[off] + 1
				if consecutive > 1 {
					fb := B[col-int(consecutive)+1]
					// Break consecutive chunk
					if b >= bonusBoundary && b > fb {
						consecutive = 1
					} else {
						b = max(b, max(bonusConsecutive, fb))
					}
				}
				if s1+b < s2 {
					s1 += Bsub[off]
					consecutive = 0
				} else {
					s1 += b
				}
			}
			Csub[off] = consecutive

			inGap = s1 < s2
			score := max(max(s1, s2), 0)
			if pidx == M-1 && (!m.Backwards && score > maxScore || m.Backwards && score >= maxScore) {
				maxScore, maxScorePos = score, col
			}
			Hsub[off] = score
		}
	}
	// Phase 4. (Optional) Backtrace to find character positions
	var pos []int
	j := f0
	if !m.Without_positions {
		pos = make([]int, 0, M)
		i := M - 1
		j = maxScorePos
		preferMatch := true
		for {
			I := i * width
			j0 := j - f0
			s := H[I+j0]

			var s1, s2 int16
			if i > 0 && j >= int(F[i]) {
				s1 = H[I-width+j0-1]
			}
			if j > int(F[i]) {
				s2 = H[I+j0-1]
			}

			if s > s1 && (s > s2 || s == s2 && preferMatch) {
				pos = append(pos, j+minIdx)
				if i == 0 {
					break
				}
				i--
			}
			preferMatch = C[I+j0] > 1 || I+width+j0+1 < len(C) && C[I+width+j0+1] > 0
			j--
		}
	}
	return Result{Score: uint(maxScore), Positions: pos}
}

func (m *FuzzyMatcher) score(items []string, pattern string, scoring_func func(string, []rune, bool, *slab, func(string) Chars) Result) (ans []Result, err error) {
	if pattern == "" || len(items) < 1 {
		return make([]Result, len(items)), nil
	}
	as_chars := CharsFromString
	if m.Ignore_accents {
		pattern = string(CharsFromStringWithoutAccents(pattern).runes)
		as_chars = CharsFromStringWithoutAccents
	}
	pattern = norm.NFC.String(pattern)
	if !m.Case_sensitive {
		pattern = strings.ToLower(pattern)
	}
	pat := []rune(pattern)
	pattern_is_ascii := !slices.ContainsFunc(pat, func(r rune) bool { return r >= utf8.RuneSelf })
	ans = make([]Result, len(items))
	err = utils.Run_in_parallel_over_range(0, func(start, end int) error {
		s := slab{}
		for i := start; i < end; i++ {
			ans[i] = scoring_func(items[i], pat, pattern_is_ascii, &s, as_chars)
		}
		return nil
	}, 0, len(items))
	return

}
