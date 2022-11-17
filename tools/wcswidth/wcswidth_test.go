// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package wcswidth

import (
	"testing"

	"github.com/google/go-cmp/cmp"
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
	wcswidth("a\x1b[22bcd", 25)
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
	truncate("a\x1b[7bb", 2, "a", 1)
	truncate("a\x1b[3bbc", 5, "a\x1b[3bb", 5)
}

func TestCellIterator(t *testing.T) {
	f := func(text string, expected ...string) {
		ci := NewCellIterator(text)
		actual := make([]string, 0, len(expected))
		for ci.Forward() {
			actual = append(actual, ci.Current())
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed forward iteration for string: %#v\n%s", text, diff)
		}
	}

	f("abc", "a", "b", "c")
	f("a🌷ò", "a", "🌷", "ò")
	f("a🌷\ufe0eò", "a", "🌷\ufe0e", "ò")
	f("òne", "ò", "n", "e")

	r := func(text string, expected ...string) {
		ci := NewCellIterator(text).GotoEnd()
		actual := make([]string, 0, len(expected))
		for ci.Backward() {
			actual = append(actual, ci.Current())
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed reverse iteration for string: %#v\n%s", text, diff)
		}
	}

	r("abc", "c", "b", "a")
	r("a🌷ò", "ò", "🌷", "a")
	r("òne", "e", "n", "ò")

	ci := NewCellIterator("123")
	ci.Forward()
	ci.Forward()
	ci.Forward()
	ci.Backward()
	if ci.Current() != "2" {
		t.Fatalf("switching to backward failed, %#v != %#v", "2", ci.Current())
	}
	ci.Backward()
	if ci.Current() != "1" {
		t.Fatalf("switching to backward failed, %#v != %#v", "1", ci.Current())
	}
	ci.Forward()
	if ci.Current() != "2" {
		t.Fatalf("switching to forward failed, %#v != %#v", "2", ci.Current())
	}
}
