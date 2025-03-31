package wcswidth

import (
	"fmt"
	"iter"
)

var _ = fmt.Print

func CharPropsFor(ch rune) CharProps {
	return charprops_t3[charprops_t2[(rune(charprops_t1[ch>>charprops_shift])<<charprops_shift)+(ch&charprops_mask)]]
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
	t1 := uint16(graphemesegmentationresult_t1[key>>graphemesegmentationresult_shift]) << graphemesegmentationresult_shift
	t2 := graphemesegmentationresult_t2[t1+key&graphemesegmentationresult_mask]
	ans := graphemesegmentationresult_t3[t2]
	// fmt.Printf("state: %d gsp: %d -> key: %d t1: %d -> add_to_cell: %d\n", s.State(), ch.GraphemeSegmentationProperty(), key, t1, ans.Add_to_current_cell())
	return ans
}

func Runewidth(code rune) int {
	return CharPropsFor(code).Width()
}

func IsEmojiPresentationBase(code rune) bool {
	return CharPropsFor(code).Is_emoji_presentation_base() == 1
}
