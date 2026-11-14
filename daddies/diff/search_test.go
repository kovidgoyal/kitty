// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"regexp"
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestDiffSearchFindMatches(t *testing.T) {
	wrapped := []string{"abc def ", "ghi rows"}
	for _, tc := range []struct {
		pat      string
		lines    []string
		origin   int
		expected [][3]int
	}{
		{"foo", []string{"x := foo"}, 0, [][3]int{{0, 5, 3}}},
		{"o", []string{"foo"}, 0, [][3]int{{0, 1, 1}, {0, 2, 1}}},
		{"rows", wrapped, 0, [][3]int{{1, 4, 4}}},
		{"def ghi", wrapped, 0, [][3]int{{0, 4, 4}, {1, 0, 3}}},
		{"def ", wrapped, 0, [][3]int{{0, 4, 4}}},
		{"foo", []string{"日本 foo"}, 0, [][3]int{{0, 5, 3}}},
		{"foo", []string{"x := foo"}, 7, [][3]int{{0, 12, 3}}},
	} {
		s := &Search{pat: regexp.MustCompile(tc.pat)}
		var actual [][3]int
		s.find_matches_in_lines(tc.lines, tc.origin, func(screen_line, offset, size int) {
			if size > 0 {
				actual = append(actual, [3]int{screen_line, offset, size})
			}
		})
		if diff := cmp.Diff(tc.expected, actual); diff != "" {
			t.Errorf("Unexpected matches for %#v in %#v:\n%s", tc.pat, tc.lines, diff)
		}
	}
}
