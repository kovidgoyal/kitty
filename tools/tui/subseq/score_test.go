// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package subseq

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/utils"
	"strconv"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestSubseq(t *testing.T) {
	var positions [][]int
	sort_by_score := false

	simple := func(items, query string, expected ...string) {
		matches := ScoreItems(query, utils.Splitlines(items), Options{})
		if sort_by_score {
			matches = utils.StableSort(matches, func(a, b *Match) int {
				if b.Score < a.Score {
					return -1
				}
				if b.Score > a.Score {
					return 1
				}
				return 0
			})
		}
		actual := make([]string, 0, len(matches))
		actual_positions := make([][]int, 0, len(matches))
		for _, m := range matches {
			if m.Score > 0 {
				actual = append(actual, m.Text)
				actual_positions = append(actual_positions, m.Positions)
			}
		}
		if expected == nil {
			expected = []string{}
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed for items: %v\nMatches: %#v\n%s", utils.Splitlines(items), matches, diff)
		}
		if positions != nil {
			if diff := cmp.Diff(positions, actual_positions); diff != "" {
				t.Fatalf("Failed positions for items: %v\n%s", utils.Splitlines(items), diff)
			}
			positions = nil
		}
	}
	simple("test\nxyz", "te", "test")
	simple("abc\nxyz", "ba")
	simple("abc\n123", "abc", "abc")
	simple("test\nxyz", "Te", "test")
	simple("test\nxyz", "XY", "xyz")
	simple("test\nXYZ", "xy", "XYZ")
	simple("test\nXYZ", "mn")

	positions = [][]int{{0, 2}, {0, 1}}
	simple("abc\nac", "ac", "abc", "ac")
	positions = [][]int{{0}}
	simple("abc\nv", "a", "abc")
	positions = [][]int{{len("汉"), 7}}
	simple("汉a字b\nxyz", "ab", "汉a字b")

	sort_by_score = true
	// Match at start
	simple("archer\nelementary", "e", "elementary", "archer")
	// Match at level factor
	simple("xxxy\nxx/y", "y", "xx/y", "xxxy")
	// CamelCase
	simple("xxxy\nxxxY", "y", "xxxY", "xxxy")
	// Total length
	simple("xxxya\nxxxy", "y", "xxxy", "xxxya")
	// Distance
	simple("abbc\nabc", "ac", "abc", "abbc")
	// Extreme chars
	simple("xxa\naxx", "a", "axx", "xxa")
	// Highest score
	positions = [][]int{{3}}
	simple("xa/a", "a", "xa/a")

	sort_by_score = false
	items := make([]string, 256)
	for i := range items {
		items[i] = strconv.Itoa(i)
	}
	expected := make([]string, 0, len(items))
	for _, x := range items {
		if strings.ContainsRune(x, rune('2')) {
			expected = append(expected, x)
		}
	}
	simple(strings.Join(items, "\n"), "2", expected...)
}
