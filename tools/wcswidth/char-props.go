package wcswidth

import (
	"fmt"
	"iter"
)

var _ = fmt.Print

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
	return GraphemeSegmentationResultFor(key)
}

func Runewidth(code rune) int {
	return CharPropsFor(code).Width()
}

func IsEmojiPresentationBase(code rune) bool {
	return CharPropsFor(code).Is_emoji_presentation_base() == 1
}
