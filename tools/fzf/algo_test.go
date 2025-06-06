package fzf

import (
	"fmt"
	"sort"
	"testing"
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
}
