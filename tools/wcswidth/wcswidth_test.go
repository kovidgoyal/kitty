// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package wcswidth

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestNonZeroWidthSpacingMarks(t *testing.T) {
	// The cell a SpacingMark with non-zero width combines into is widened, both here and
	// in kitty's C code. Only U+0E33 and U+0EB3 have that combination of properties, which
	// docs/text-sizing-protocol.rst specifies, so guard against a Unicode data refresh
	// silently changing the set.
	expected := map[rune]bool{0x0e33: true, 0x0eb3: true}
	for r := rune(0); r <= MAX_UNICODE; r++ {
		cp := CharPropsFor(r)
		if cp.Grapheme_break() == uint8(GBP_SpacingMark) && cp.Width() > 0 {
			if !expected[r] {
				t.Fatalf("U+%04X is an unexpected non-zero width SpacingMark of width: %d", r, cp.Width())
			}
			delete(expected, r)
		}
	}
	for r := range expected {
		t.Fatalf("U+%04X is no longer a non-zero width SpacingMark", r)
	}
}

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
	// Spacing marks widen the cell they are added to, see the Spacing marks section of the text sizing protocol
	// Thai SARA AM
	wcswidth("\u0e08\u0e33", 2)
	wcswidth("\u0e33", 1)
	// a nonspacing mark adds no width
	wcswidth("\u0e01\u0e34", 1)
	wcswidth("\u0e08\u0e33\u0e33", 3)
	// Lao AM
	wcswidth("\u0e81\u0eb3", 2)
	// Devanagari vowel sign I, which is to the left of its base
	wcswidth("\u0915\u093f", 2)
	// visarga
	wcswidth("\u0937\u0903", 2)
	wcswidth("\u0937\u0903\u0903", 3)
	// Tamil AA, a spacing mark with Grapheme_Cluster_Break=Extend
	wcswidth("\u0b95\u0bbe", 2)
	// Tamil O, a two part vowel, has a spacing width of two
	wcswidth("\u0b9f\u0bca", 3)
	// and its decomposed form has the same width
	wcswidth("\u0b9f\u0bc6\u0bbe", 3)
	// Myanmar AA follows a grapheme break, it is added to the previous cell
	wcswidth("\u1000\u1031\u102c", 3)
	wcswidth("\u1019\u1039\u1018\u102c\u1037", 2)
	// Bengali: consonant, two part vowel and anusvara
	wcswidth("\u0995\u09cb\u0982", 4)
	// the width is capped at four
	wcswidth("\u0937\u0903\u0903\u0903\u0903\u0903\u0903", 4)
	// halfwidth katakana voiced sound mark
	wcswidth("\uff76\uff9e", 2)
	// a letter that decomposes into a letter and a spacing mark
	wcswidth("\u0b94", 2)
	// spacing marks with combining classes other than 0 and 9 add no width
	wcswidth("\U0001d158\U0001d165\U0001d16e", 1)
	wcswidth("\uac00\u302e", 2)
	// regardless of the base
	wcswidth("\U0001f600\u093e", 3)
	// VS16 after a spacing mark has no effect
	wcswidth("\u0915\u0903\ufe0f", 2)
	// a spacing mark after VS15 widens the narrowed emoji
	wcswidth("\u231a\ufe0e\u093e", 2)
	// a spacing mark with no base is in a cell of its own
	wcswidth("\u093f", 1)
	wcswidth("\u0bca", 2)
	wcswidth("\u094d\u0903", 1)
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
