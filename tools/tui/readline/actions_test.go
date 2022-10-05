// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"
	"kitty/tools/tui/loop"
	"testing"
)

var _ = fmt.Print

func TestAddText(t *testing.T) {
	lp, _ := loop.New()

	dt := func(initial string, prepare func(rl *Readline), expected ...string) {
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
	}

	dt("test", nil, "test", "", "test")
	dt("1234\n", nil, "1234\n", "", "1234\n")
	dt("abcd", func(rl *Readline) {
		rl.cursor_pos_in_line = 2
		rl.add_text("12")
	}, "ab12", "cd", "ab12cd")
	dt("abcd", func(rl *Readline) {
		rl.cursor_pos_in_line = 2
		rl.add_text("12\n34")
	}, "ab12\n34", "cd", "ab12\n34cd")
	dt("abcd\nxyz", func(rl *Readline) {
		rl.cursor_pos_in_line = 2
		rl.add_text("12\n34")
	}, "abcd\nxy12\n34", "z", "abcd\nxy12\n34z")

}
