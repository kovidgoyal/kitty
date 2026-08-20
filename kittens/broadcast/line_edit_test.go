// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package broadcast

import "testing"

func TestLineEdit(t *testing.T) {
	le := line_edit{}
	le.on_text("hello")
	if le.String() != "hello" || le.cursor != 5 {
		t.Fatalf("insert failed: %q cursor=%d", le.String(), le.cursor)
	}
	le.backspace()
	if le.String() != "hell" {
		t.Fatalf("backspace failed: %q", le.String())
	}
	le.left()
	le.left()
	le.on_text("X")
	if le.String() != "heXll" || le.cursor != 3 {
		t.Fatalf("mid-insert failed: %q cursor=%d", le.String(), le.cursor)
	}
	le.home()
	if le.cursor != 0 {
		t.Fatal("home failed")
	}
	le.end()
	if le.cursor != 5 {
		t.Fatal("end failed")
	}
	le.clear()
	if le.String() != "" || le.cursor != 0 {
		t.Fatal("clear failed")
	}
}
