package choose_files

import (
	"fmt"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestSplitWithPositions(t *testing.T) {
	for _, c := range []struct {
		src       string
		positions []int
		expected  []string
	}{
		{"abc", nil, []string{"abc"}},
		{"abc", []int{0}, []string{"a", "bc"}},
		{"abc", []int{1}, []string{"a", "b", "c"}},
		{"abc", []int{2}, []string{"ab", "c"}},
		{"abc", []int{0, 1}, []string{"a", "b", "c"}},
		{"abc", []int{0, 1, 2}, []string{"a", "b", "c"}},
		{"abc", []int{0, 2}, []string{"a", "b", "c"}},
		// invalid positions
		{"abc", []int{-1}, []string{"abc"}},
		{"abc", []int{3}, []string{"abc"}},
		{"abc", []int{0, 3}, []string{"a", "bc"}},
		{"abc", []int{2, 0}, []string{"ab", "c"}},
		{"abc", []int{2, 1}, []string{"ab", "c"}},
		{"abc", []int{1, 0}, []string{"a", "b", "c"}},
	} {
		actual := make([]string, 0, len(c.expected))
		for ch := range split_up_text(c.src, false, c.positions) {
			actual = append(actual, ch.text)
		}
		if diff := cmp.Diff(c.expected, actual); diff != "" {
			t.Fatalf("Failed for src: %#v positions: %v\n%s", c.src, c.positions, diff)
		}
	}
}
