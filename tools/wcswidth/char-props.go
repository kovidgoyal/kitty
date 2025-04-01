package wcswidth

import (
	"fmt"
	"iter"
)

var _ = fmt.Print

func ensure_char_in_range(value uint32) uint32 {
	// Branchless: if (value > MAX_UNICODE) value = 0
	diff := int64(value) - UNICODE_LIMIT
	// The right shift gives all ones for negative diff and all zeros for positive diff
	mask := uint32(diff >> 63)
	return value & mask
}

func CharPropsFor(ch rune) CharProps {
	q := ensure_char_in_range(uint32(ch))
	return charprops_for(q)
}

func IteratorOverGraphemes(text string) iter.Seq[string] {
	var s GraphemeSegmentationResult
	start_pos := 0
	return func(yield func(string) bool) {
		for pos, ch := range text {
			if s = s.Step(CharPropsFor(ch)); s.Add_to_current_cell() == 0 {
				if !yield(text[start_pos:pos]) {
					return
				}
				start_pos = pos
			}
		}
		if start_pos < len(text) {
			yield(text[start_pos:])
		}
	}
}

func SplitIntoGraphemes(text string) []string {
	ans := make([]string, 0, len(text))
	for t := range IteratorOverGraphemes(text) {
		ans = append(ans, t)
	}
	return ans
}

func (s *GraphemeSegmentationResult) Reset() {
	*s = 0
}

func (s GraphemeSegmentationResult) Step(ch CharProps) GraphemeSegmentationResult {
	key := grapheme_segmentation_key(s, ch)
	return graphemesegmentationresult_for(key)
}

func Runewidth(code rune) int {
	return CharPropsFor(code).Width()
}

func IsEmojiPresentationBase(code rune) bool {
	return CharPropsFor(code).Is_emoji_presentation_base() == 1
}
