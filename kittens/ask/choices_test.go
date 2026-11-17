// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package ask

import (
	"strings"
	"testing"
	"unicode/utf8"
)

func TestAskTruncateAtSpace(t *testing.T) {
	for _, tc := range []struct {
		text        string
		width       int
		first, rest string
	}{
		{"hello world", 20, "hello world", ""},
		{"hello world", 8, "hello ", "world"},
		// width is in cells, the split must not be computed in bytes
		{"ééééé ééééé", 8, "ééééé ", "ééééé"},
		// a character wider than the available width must still be consumed
		{"中文", 1, "中", "文"},
	} {
		first, rest := truncate_at_space(tc.text, tc.width)
		if first != tc.first || rest != tc.rest {
			t.Fatalf("truncate_at_space(%q, %d) = (%q, %q), expected (%q, %q)", tc.text, tc.width, first, rest, tc.first, tc.rest)
		}
	}
	// Wrapping must always terminate and produce valid UTF-8
	text := strings.Repeat("中é ", 20)
	for width := 1; width < 10; width++ {
		remaining := text
		for i := 0; remaining != ""; i++ {
			if i > len(text) {
				t.Fatalf("truncate_at_space made no progress at width %d", width)
			}
			var line string
			line, remaining = truncate_at_space(remaining, width)
			if !utf8.ValidString(line) {
				t.Fatalf("truncate_at_space produced invalid UTF-8 at width %d: %q", width, line)
			}
		}
	}
}
