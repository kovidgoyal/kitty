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

	truncate := func(text string, length int, expected string, expected_width int) {
		actual, actual_width := TruncateToVisualLengthWithWidth(text, length)
		if actual != expected {
			t.Fatalf("Failed to truncate \"%s\" to %d\nExpected: %#v\nActual:   %#v", text, length, expected, actual)
		}
		if actual_width != expected_width {
			t.Fatalf("Failed to truncate with width \"%s\" to %d\nExpected: %d\nActual:   %d", text, length, expected_width, actual_width)
		}
	}
	truncate("abc", 4, "abc", 3)
	truncate("abc", 3, "abc", 3)
	truncate("abc", 2, "ab", 2)
	truncate("abc", 0, "", 0)
	truncate("a🌷", 2, "a", 1)
	truncate("a🌷", 3, "a🌷", 3)
	truncate("a🌷b", 3, "a🌷", 3)
	truncate("a🌷b", 4, "a🌷b", 4)
	truncate("a🌷\ufe0e", 2, "a🌷\ufe0e", 2)
	truncate("a🌷\ufe0eb", 3, "a🌷\ufe0eb", 3)
	truncate("a\x1b[31mb", 2, "a\x1b[31mb", 2)
}
