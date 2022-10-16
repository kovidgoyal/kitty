// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"
	"kitty/tools/tui/loop"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func test_func(t *testing.T) func(string, func(*Readline), ...string) *Readline {
	return func(initial string, prepare func(rl *Readline), expected ...string) *Readline {
		lp, _ := loop.New()
		rl := New(lp, RlInit{})
		rl.add_text(initial)
		if prepare != nil {
			prepare(rl)
		}
		if len(expected) > 0 {
			if expected[0] != rl.text_upto_cursor_pos() {
				t.Fatalf("Text upto cursor pos not as expected for: %#v\n%#v != %#v", initial, expected[0], rl.text_upto_cursor_pos())
			}
		}
		if len(expected) > 1 {
			if expected[1] != rl.text_after_cursor_pos() {
				t.Fatalf("Text after cursor pos not as expected for: %#v\n%#v != %#v", initial, expected[1], rl.text_after_cursor_pos())
			}
		}
		if len(expected) > 2 {
			if expected[2] != rl.all_text() {
				t.Fatalf("Text not as expected for: %#v\n%#v != %#v", initial, expected[2], rl.all_text())
			}
		}
		return rl
	}

}

func TestAddText(t *testing.T) {
	dt := test_func(t)
	dt("test", nil, "test", "", "test")
	dt("1234\n", nil, "1234\n", "", "1234\n")
	dt("abcd", func(rl *Readline) {
		rl.cursor.X = 2
		rl.add_text("12")
	}, "ab12", "cd", "ab12cd")
	dt("abcd", func(rl *Readline) {
		rl.cursor.X = 2
		rl.add_text("12\n34")
	}, "ab12\n34", "cd", "ab12\n34cd")
	dt("abcd\nxyz", func(rl *Readline) {
		rl.cursor.X = 2
		rl.add_text("12\n34")
	}, "abcd\nxy12\n34", "z", "abcd\nxy12\n34z")
}

func TestGetScreenLines(t *testing.T) {
	lp, _ := loop.New()
	rl := New(lp, RlInit{Prompt: "$$ "})
	rl.screen_width = 10

	tsl := func(expected ...ScreenLine) {
		q := rl.get_screen_lines()
		actual := make([]ScreenLine, len(q))
		for i, x := range q {
			actual[i] = *x
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Did not get expected screen lines for: %#v and cursor: %+v\n%s", rl.AllText(), rl.cursor, diff)
		}
	}
	tsl(ScreenLine{PromptLen: 3, CursorCell: 3})
	rl.add_text("123")
	tsl(ScreenLine{PromptLen: 3, CursorCell: 6, Text: "123", CursorTextPos: 3, TextLengthInCells: 3})
	rl.add_text("456")
	tsl(ScreenLine{PromptLen: 3, CursorCell: 9, Text: "123456", CursorTextPos: 6, TextLengthInCells: 6})
	rl.add_text("7")
	tsl(
		ScreenLine{PromptLen: 3, CursorCell: -1, Text: "1234567", CursorTextPos: -1, TextLengthInCells: 7},
		ScreenLine{OffsetInParentLine: 7},
	)
	rl.add_text("89")
	tsl(
		ScreenLine{PromptLen: 3, CursorCell: -1, Text: "1234567", CursorTextPos: -1, TextLengthInCells: 7},
		ScreenLine{OffsetInParentLine: 7, Text: "89", CursorCell: 2, TextLengthInCells: 2, CursorTextPos: 2},
	)
	rl.ResetText()
	rl.add_text("123\n456abcdeXYZ")
	tsl(
		ScreenLine{PromptLen: 3, CursorCell: -1, Text: "123", CursorTextPos: -1, TextLengthInCells: 3},
		ScreenLine{ParentLineNumber: 1, PromptLen: 2, Text: "456abcde", TextLengthInCells: 8, CursorCell: -1, CursorTextPos: -1},
		ScreenLine{OffsetInParentLine: 8, ParentLineNumber: 1, TextLengthInCells: 3, CursorCell: 3, CursorTextPos: 3, Text: "XYZ"},
	)
	rl.cursor = Position{X: 2}
	tsl(
		ScreenLine{PromptLen: 3, CursorCell: 5, Text: "123", CursorTextPos: 2, TextLengthInCells: 3},
		ScreenLine{ParentLineNumber: 1, PromptLen: 2, Text: "456abcde", TextLengthInCells: 8, CursorCell: -1, CursorTextPos: -1},
		ScreenLine{OffsetInParentLine: 8, ParentLineNumber: 1, TextLengthInCells: 3, CursorCell: -1, CursorTextPos: -1, Text: "XYZ"},
	)
	rl.cursor = Position{X: 2, Y: 1}
	tsl(
		ScreenLine{PromptLen: 3, CursorCell: -1, Text: "123", CursorTextPos: -1, TextLengthInCells: 3},
		ScreenLine{ParentLineNumber: 1, PromptLen: 2, Text: "456abcde", TextLengthInCells: 8, CursorCell: 4, CursorTextPos: 2},
		ScreenLine{OffsetInParentLine: 8, ParentLineNumber: 1, TextLengthInCells: 3, CursorCell: -1, CursorTextPos: -1, Text: "XYZ"},
	)
	rl.cursor = Position{X: 8, Y: 1}
	tsl(
		ScreenLine{PromptLen: 3, CursorCell: -1, Text: "123", CursorTextPos: -1, TextLengthInCells: 3},
		ScreenLine{ParentLineNumber: 1, PromptLen: 2, Text: "456abcde", TextLengthInCells: 8, CursorCell: -1, CursorTextPos: -1},
		ScreenLine{OffsetInParentLine: 8, ParentLineNumber: 1, TextLengthInCells: 3, CursorCell: 0, CursorTextPos: 0, Text: "XYZ"},
	)
	rl.ResetText()
	rl.add_text("1234567\nabc")
	rl.cursor = Position{X: 7}
	tsl(
		ScreenLine{PromptLen: 3, CursorCell: -1, Text: "1234567", CursorTextPos: -1, TextLengthInCells: 7},
		ScreenLine{ParentLineNumber: 1, PromptLen: 2, Text: "abc", CursorCell: 2, TextLengthInCells: 3, CursorTextPos: 0},
	)
}

func TestCursorMovement(t *testing.T) {
	dt := test_func(t)

	left := func(rl *Readline, amt uint, moved_amt uint, traverse_line_breaks bool) {
		actual := rl.move_cursor_left(amt, traverse_line_breaks)
		if actual != moved_amt {
			t.Fatalf("Failed to move cursor by %#v\nactual != expected: %#v != %#v", amt, actual, moved_amt)
		}
	}
	dt("one\ntwo", func(rl *Readline) {
		left(rl, 2, 2, false)
	}, "one\nt", "wo")
	dt("one\ntwo", func(rl *Readline) {
		left(rl, 4, 3, false)
	}, "one\n", "two")
	dt("one\ntwo", func(rl *Readline) {
		left(rl, 4, 4, true)
	}, "one", "\ntwo")
	dt("one\ntwo", func(rl *Readline) {
		left(rl, 7, 7, true)
	}, "", "one\ntwo")
	dt("one\ntwo", func(rl *Readline) {
		left(rl, 10, 7, true)
	}, "", "one\ntwo")
	dt("one😀", func(rl *Readline) {
		left(rl, 1, 1, false)
	}, "one", "😀")
	dt("oneà", func(rl *Readline) {
		left(rl, 1, 1, false)
	}, "one", "à")

	right := func(rl *Readline, amt uint, moved_amt uint, traverse_line_breaks bool) {
		rl.cursor.Y = 0
		rl.cursor.X = 0
		actual := rl.move_cursor_right(amt, traverse_line_breaks)
		if actual != moved_amt {
			t.Fatalf("Failed to move cursor by %#v\nactual != expected: %#v != %#v", amt, actual, moved_amt)
		}
	}
	dt("one\ntwo", func(rl *Readline) {
		right(rl, 2, 2, false)
	}, "on", "e\ntwo")
	dt("one\ntwo", func(rl *Readline) {
		right(rl, 4, 3, false)
	}, "one", "\ntwo")
	dt("one\ntwo", func(rl *Readline) {
		right(rl, 4, 4, true)
	}, "one\n", "two")
	dt("😀one", func(rl *Readline) {
		right(rl, 1, 1, false)
	}, "😀", "one")
	dt("àb", func(rl *Readline) {
		right(rl, 1, 1, false)
	}, "à", "b")
}

func TestEraseChars(t *testing.T) {
	dt := test_func(t)

	backspace := func(rl *Readline, amt uint, erased_amt uint, traverse_line_breaks bool) {
		actual := rl.erase_chars_before_cursor(amt, traverse_line_breaks)
		if actual != erased_amt {
			t.Fatalf("Failed to move cursor by %#v\nactual != expected: %d != %d", amt, actual, erased_amt)
		}
	}
	dt("one\ntwo", func(rl *Readline) {
		backspace(rl, 2, 2, false)
	}, "one\nt", "")
	dt("one\ntwo", func(rl *Readline) {
		rl.cursor.X = 1
		backspace(rl, 2, 1, false)
	}, "one\n", "wo")
	dt("one\ntwo", func(rl *Readline) {
		rl.cursor.X = 1
		backspace(rl, 2, 2, true)
	}, "one", "wo")
	dt("a😀", func(rl *Readline) {
		backspace(rl, 1, 1, false)
	}, "a", "")
	dt("bà", func(rl *Readline) {
		backspace(rl, 1, 1, false)
	}, "b", "")

	del := func(rl *Readline, amt uint, erased_amt uint, traverse_line_breaks bool) {
		rl.cursor.Y = 0
		rl.cursor.X = 0
		actual := rl.erase_chars_after_cursor(amt, traverse_line_breaks)
		if actual != erased_amt {
			t.Fatalf("Failed to move cursor by %#v\nactual != expected: %d != %d", amt, actual, erased_amt)
		}
	}
	dt("one\ntwo", func(rl *Readline) {
		del(rl, 2, 2, false)
	}, "", "e\ntwo")
	dt("😀a", func(rl *Readline) {
		del(rl, 1, 1, false)
	}, "", "a")
	dt("àb", func(rl *Readline) {
		del(rl, 1, 1, false)
	}, "", "b")

	dt("one\ntwo\nthree", func(rl *Readline) {
		rl.erase_between(Position{X: 1}, Position{X: 2, Y: 2})
	}, "oree", "")
	dt("one\ntwo\nthree", func(rl *Readline) {
		rl.cursor.X = 1
		rl.erase_between(Position{X: 1}, Position{X: 2, Y: 2})
	}, "o", "ree")
	dt("one\ntwo\nthree", func(rl *Readline) {
		rl.cursor = Position{X: 1, Y: 1}
		rl.erase_between(Position{X: 1}, Position{X: 2, Y: 2})
	}, "o", "ree")
	dt("one\ntwo\nthree", func(rl *Readline) {
		rl.cursor = Position{X: 1, Y: 0}
		rl.erase_between(Position{X: 1}, Position{X: 2, Y: 2})
	}, "o", "ree")
	dt("one\ntwo\nthree", func(rl *Readline) {
		rl.cursor = Position{X: 0, Y: 0}
		rl.erase_between(Position{X: 1}, Position{X: 2, Y: 2})
	}, "", "oree")
}
