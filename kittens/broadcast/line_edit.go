// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package broadcast

import "github.com/kovidgoyal/kitty/tools/tui/loop"

// Minimal line editor: covers the subset of kittens/tui/line_edit.py that
// the broadcast kitten actually uses (insert, backspace, arrows, home/end).
type line_edit struct {
	text   []rune
	cursor int
}

func (l *line_edit) String() string { return string(l.text) }

func (l *line_edit) on_text(t string) {
	r := []rune(t)
	l.text = append(l.text[:l.cursor], append(r, l.text[l.cursor:]...)...)
	l.cursor += len(r)
}

func (l *line_edit) backspace() bool {
	if l.cursor == 0 {
		return false
	}
	l.text = append(l.text[:l.cursor-1], l.text[l.cursor:]...)
	l.cursor--
	return true
}

func (l *line_edit) left() {
	if l.cursor > 0 {
		l.cursor--
	}
}
func (l *line_edit) right() {
	if l.cursor < len(l.text) {
		l.cursor++
	}
}
func (l *line_edit) home() { l.cursor = 0 }
func (l *line_edit) end()  { l.cursor = len(l.text) }
func (l *line_edit) clear() {
	l.text = l.text[:0]
	l.cursor = 0
}

// on_key returns true if the key was consumed as an editing action.
func (l *line_edit) on_key(e *loop.KeyEvent) bool {
	switch {
	case e.MatchesPressOrRepeat("backspace"):
		e.Handled = true
		return l.backspace()
	case e.MatchesPressOrRepeat("left"):
		e.Handled = true
		l.left()
		return true
	case e.MatchesPressOrRepeat("right"):
		e.Handled = true
		l.right()
		return true
	case e.MatchesPressOrRepeat("home"), e.MatchesPressOrRepeat("ctrl+a"):
		e.Handled = true
		l.home()
		return true
	case e.MatchesPressOrRepeat("end"), e.MatchesPressOrRepeat("ctrl+e"):
		e.Handled = true
		l.end()
		return true
	}
	return false
}

// write draws the current line and positions the cursor.
func (l *line_edit) write(lp *loop.Loop) {
	lp.QueueWriteString(string(l.text))
	if diff := len(l.text) - l.cursor; diff > 0 {
		lp.MoveCursorHorizontally(-diff)
	}
}
