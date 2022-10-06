// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"
	"kitty/tools/tui/loop"
	"testing"
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
