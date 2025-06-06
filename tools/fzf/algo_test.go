package fzf

import (
	"cmp"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"testing"

	gcmp "github.com/google/go-cmp/cmp"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func assertMatch(t *testing.T, m *FuzzyMatcher, item string, query string, start, end, score int) {
	r, err := m.Score([]string{item}, query)
	if err != nil {
		t.Fatal(err)
	}
	if r[0].Score != uint(score) {
		t.Fatalf("Score of %#v in %#v is %d instead of %d", query, item, r[0].Score, score)
	}
	if start > -1 && end > -1 {
		p := r[0].Positions
		sort.Ints(p)
		if len(p) < 1 {
			t.Fatalf("Got no positions for %#v in %#v", query, item)
		}
		if p[0] != start {
			t.Fatalf("First char of %#v in %#v at %d instead of %d", query, item, p[0], start)
		}
		if p[len(p)-1]+1 != end {
			t.Fatalf("Last char of %#v in %#v at %d instead of %d", query, item, p[len(p)-1], end-1)
		}
	}
}

func TestFZFAlgo(t *testing.T) {
	fn := NewFuzzyMatcher(DEFAULT_SCHEME)
	for _, forward := range []bool{true, false} {
		fn.Backwards = !forward
		fn.Case_sensitive = false
		assertMatch(t, fn, "fooBarbaz1", "oBZ", 2, 9,
			scoreMatch*3+bonusCamel123+scoreGapStart+scoreGapExtension*3)
		assertMatch(t, fn, "foo bar baz", "fbb", 0, 9,
			scoreMatch*3+int(fn.bonusBoundaryWhite)*bonusFirstCharMultiplier+
				int(fn.bonusBoundaryWhite)*2+2*scoreGapStart+4*scoreGapExtension)
		assertMatch(t, fn, "/AutomatorDocument.icns", "rdoc", 9, 13,
			scoreMatch*4+bonusCamel123+bonusConsecutive*2)
		assertMatch(t, fn, "/man1/zshcompctl.1", "zshc", 6, 10,
			scoreMatch*4+int(fn.bonusBoundaryDelimiter)*bonusFirstCharMultiplier+int(fn.bonusBoundaryDelimiter)*3)
		assertMatch(t, fn, "/.oh-my-zsh/cache", "zshc", 8, 13,
			scoreMatch*4+bonusBoundary*bonusFirstCharMultiplier+bonusBoundary*2+scoreGapStart+int(fn.bonusBoundaryDelimiter))
		assertMatch(t, fn, "ab0123 456", "12356", 3, 10,
			scoreMatch*5+bonusConsecutive*3+scoreGapStart+scoreGapExtension)
		assertMatch(t, fn, "abc123 456", "12356", 3, 10,
			scoreMatch*5+bonusCamel123*bonusFirstCharMultiplier+bonusCamel123*2+bonusConsecutive+scoreGapStart+scoreGapExtension)
		assertMatch(t, fn, "foo/bar/baz", "fbb", 0, 9,
			scoreMatch*3+int(fn.bonusBoundaryWhite)*bonusFirstCharMultiplier+
				int(fn.bonusBoundaryDelimiter)*2+2*scoreGapStart+4*scoreGapExtension)
		assertMatch(t, fn, "fooBarBaz", "fbb", 0, 7,
			scoreMatch*3+int(fn.bonusBoundaryWhite)*bonusFirstCharMultiplier+
				bonusCamel123*2+2*scoreGapStart+2*scoreGapExtension)
		assertMatch(t, fn, "foo barbaz", "fbb", 0, 8,
			scoreMatch*3+int(fn.bonusBoundaryWhite)*bonusFirstCharMultiplier+int(fn.bonusBoundaryWhite)+
				scoreGapStart*2+scoreGapExtension*3)
		assertMatch(t, fn, "fooBar Baz", "foob", 0, 4,
			scoreMatch*4+int(fn.bonusBoundaryWhite)*bonusFirstCharMultiplier+int(fn.bonusBoundaryWhite)*3)
		assertMatch(t, fn, "xFoo-Bar Baz", "foo-b", 1, 6,
			scoreMatch*5+bonusCamel123*bonusFirstCharMultiplier+bonusCamel123*2+
				bonusNonWord+bonusBoundary)

		fn.Case_sensitive = true
		assertMatch(t, fn, "fooBarbaz", "oBz", 2, 9,
			scoreMatch*3+bonusCamel123+scoreGapStart+scoreGapExtension*3)
		assertMatch(t, fn, "Foo/Bar/Baz", "FBB", 0, 9,
			scoreMatch*3+int(fn.bonusBoundaryWhite)*bonusFirstCharMultiplier+int(fn.bonusBoundaryDelimiter)*2+
				scoreGapStart*2+scoreGapExtension*4)
		assertMatch(t, fn, "FooBarBaz", "FBB", 0, 7,
			scoreMatch*3+int(fn.bonusBoundaryWhite)*bonusFirstCharMultiplier+bonusCamel123*2+
				scoreGapStart*2+scoreGapExtension*2)
		assertMatch(t, fn, "FooBar Baz", "FooB", 0, 4,
			scoreMatch*4+int(fn.bonusBoundaryWhite)*bonusFirstCharMultiplier+int(fn.bonusBoundaryWhite)*2+
				max(bonusCamel123, int(fn.bonusBoundaryWhite)))

		// Consecutive bonus updated
		assertMatch(t, fn, "foo-bar", "o-ba", 2, 6, scoreMatch*4+bonusBoundary*3)

		// Non-match
		assertMatch(t, fn, "fooBarbaz", "oBZ", -1, -1, 0)
		assertMatch(t, fn, "Foo Bar Baz", "fbb", -1, -1, 0)
		assertMatch(t, fn, "fooBarbaz", "fooBarbazz", -1, -1, 0)
	}

	var positions [][]int
	sort_by_score := false
	fn.Case_sensitive = false

	simple := func(items, query string, expected ...string) {
		ilist := utils.Splitlines(items)
		matches, err := fn.Score(ilist, query)
		if err != nil {
			t.Fatal(err)
		}
		if sort_by_score {
			slist := make([]int, len(matches))
			for i := range len(slist) {
				slist[i] = i
			}
			utils.StableSort(slist, func(a, b int) int {
				return cmp.Compare(matches[b].Score, matches[a].Score)
			})
			nlist, nmatches := make([]string, len(ilist)), make([]Result, len(matches))
			for i, j := range slist {
				nlist[i] = ilist[j]
				nmatches[i] = matches[j]
			}
			ilist = nlist
			matches = nmatches
		}
		actual := make([]string, 0, len(matches))
		actual_positions := make([][]int, 0, len(matches))
		for i, m := range matches {
			if m.Score > 0 {
				sort.Ints(m.Positions)
				actual = append(actual, ilist[i])
				actual_positions = append(actual_positions, m.Positions)
			}
		}
		if expected == nil {
			expected = []string{}
		}

		if diff := gcmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed for items: %#v\nQuery: %#v\nMatches: %#v\n%s", ilist, query, matches, diff)
		}
		if positions != nil {
			if diff := gcmp.Diff(positions, actual_positions); diff != "" {
				t.Fatalf("Failed positions for items: %v\n%s", ilist, diff)
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
	positions = [][]int{{1, 3}}
	simple("汉a字b\nxyz", "ab", "汉a字b")

	sort_by_score = true
	// Match at start
	simple("archer\nelementary", "e", "elementary", "archer")
	// Match at level factor
	simple("xxxy\nxx/y", "y", "xx/y", "xxxy")
	// CamelCase
	simple("xxxy\nxxxY", "y", "xxxY", "xxxy")
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
