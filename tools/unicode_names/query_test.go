// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package unicode_names

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/utils"
	"slices"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestUnicodeInputQueries(t *testing.T) {
	ts := func(query string, expected ...rune) {
		if expected == nil {
			expected = make([]rune, 0)
		}
		expected = utils.Sort(expected, func(a, b rune) int { return int(a) - int(b) })
		actual := CodePointsForQuery(query)
		actual = utils.Sort(actual, func(a, b rune) int { return int(a) - int(b) })
		diff := cmp.Diff(expected, actual)
		if diff != "" {
			t.Fatalf("Failed query: %#v\n%s", query, diff)
		}
	}
	ts("horiz ell", 0x2026, 0x22ef, 0x2b2c, 0x2b2d, 0xfe19)
	ts("horizontal ell", 0x2026, 0x22ef, 0x2b2c, 0x2b2d, 0xfe19)
	ts("kfjhgkjdsfhgkjds")
	if slices.Index(CodePointsForQuery("bee"), 0x1f41d) < 0 {
		t.Fatalf("The query bee did not match the codepoint: 0x1f41d")
	}
}
