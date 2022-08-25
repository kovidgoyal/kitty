// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package wcswidth

import (
	"testing"
)

func TestWCSWidth(t *testing.T) {

	wcswidth := func(text string, expected int) {
		if w := Stringwidth(text); w != expected {
			t.Fatalf("The width for %#v was %d instead of %d", text, w, expected)
		}
	}
	wcwidth := func(text string, widths ...int) {
		for i, q := range []rune(text) {
			if w := Runewidth(q); w != widths[i] {
				t.Fatalf("The width of the char: U+%x was %d instead of %d", q, w, widths[i])
			}
		}
	}

	wcwidth("a1\000コニチ ✔", 1, 1, 0, 2, 2, 2, 1, 1)
	wcswidth("a\033[2mb", 2)
	wcswidth("\033a\033[2mb", 2)
	wcswidth("a\033]8;id=moo;https://foo\033\\a", 2)
	wcswidth("a\033x", 2)
	wcswidth("\u2716\u2716\ufe0f\U0001f337", 5)
	wcswidth("\u25b6\ufe0f", 2)
	wcswidth("\U0001f610\ufe0e", 1)
	wcswidth("\U0001f1e6a", 3)
	wcswidth("\U0001F1E6a\U0001F1E8a", 6)
	wcswidth("\U0001F1E6\U0001F1E8a", 3)
	wcswidth("\U0001F1E6\U0001F1E8\U0001F1E6", 4)
	wcswidth("a\u00adb", 2)
	// Flags individually and together
	wcwidth("\U0001f1ee\U0001f1f3", 2, 2)
	wcswidth("\U0001f1ee\U0001f1f3", 2)
}
