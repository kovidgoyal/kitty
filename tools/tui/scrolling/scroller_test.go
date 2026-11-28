// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package scrolling

import (
	"fmt"
	"slices"
	"testing"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print

func TestRowShift(t *testing.T) {
	for _, tc := range []struct{ offset, h, d, shift, new_offset int }{
		{0, 20, 0, 0, 0},
		// The row moving in is moved into the rectangle before it is visible
		{0, 20, 1, 1, 19},
		{19, 20, -1, -1, 0},
		{0, 20, 20, 1, 0},
		{0, 20, 21, 2, 19},
		{0, 20, -1, -1, -19},
		{-19, 20, 1, 1, 0},
		{5, 20, -100, -6, -15},
		{5, 20, 3, 0, 2},
		{-5, 20, -3, 0, -2},
	} {
		shift, offset := RowShift(tc.offset, tc.h, tc.d)
		if shift != tc.shift || offset != tc.new_offset {
			t.Fatalf("RowShift(%d, %d, %d) = (%d, %d) != (%d, %d)", tc.offset, tc.h, tc.d, shift, offset, tc.shift, tc.new_offset)
		}
	}
}

type painted struct{ row, line int }

func new_test_scroller(supported bool) (*Scroller, *loop.Loop, *[]painted) {
	lp, _ := loop.New()
	var p []painted
	s := &Scroller{Id: 1, Paint: func(row, line int) { p = append(p, painted{row, line}) }}
	if supported {
		s.SetSupported()
	}
	s.SetNumLines(100)
	s.SetGeometry(0, 2, 10, 5, 10)
	return s, lp, &p
}

func TestScroller(t *testing.T) {
	s, lp, p := new_test_scroller(true)
	check := func(first_line, offset int, expected ...painted) {
		t.Helper()
		if s.FirstLine() != first_line || s.Offset() != offset {
			t.Fatalf("Incorrect position: first_line=%d offset=%d expected first_line=%d offset=%d", s.FirstLine(), s.Offset(), first_line, offset)
		}
		if !slices.Equal(*p, expected) {
			t.Fatalf("Incorrect rows painted:\n%v\nexpected:\n%v", *p, expected)
		}
		*p = (*p)[:0]
	}
	if s.ScrollPixels(lp, 5) {
		t.Fatalf("Scrolled before being drawn")
	}
	s.Draw(lp)
	check(0, 0, painted{0, 0}, painted{1, 1}, painted{2, 2}, painted{3, 3}, painted{4, 4})
	if s.ScrollPixels(lp, -1) {
		t.Fatalf("Scrolled before the start")
	}
	s.ScrollPixels(lp, 3)
	check(1, 7, painted{4, 5})
	s.ScrollPixels(lp, 2)
	check(1, 5)
	// Scrolling back moves the row back into the rectangle
	s.ScrollPixels(lp, -4)
	check(0, -1, painted{0, 0})
	if s.Position() != 1 {
		t.Fatalf("Incorrect position: %d", s.Position())
	}
	// Fractional lines are accumulated
	s.ScrollLines(lp, 0.05)
	check(0, -1)
	s.ScrollLines(lp, 0.05)
	check(1, 8, painted{4, 5})
	// Scrolling by more than the height paints all rows
	s.ScrollToLine(lp, 50)
	check(50, 0, painted{0, 50}, painted{1, 51}, painted{2, 52}, painted{3, 53}, painted{4, 54})
	// Scrolling is limited to the content
	s.ScrollPixels(lp, 10000)
	if s.Position() != s.MaxPosition() || s.MaxPosition() != 950 || s.FirstLine() != 95 {
		t.Fatalf("Incorrect position at the end: %d", s.Position())
	}
	*p = (*p)[:0]
	if s.ScrollPixels(lp, 1) || s.ScrollLines(lp, 1) {
		t.Fatalf("Scrolled past the end")
	}
	// Redrawing paints the partially visible row as well
	s.ScrollPixels(lp, -3)
	check(94, -7, painted{0, 94})
	s.RedrawAll(lp)
	check(94, -7, painted{0, 94}, painted{1, 95}, painted{2, 96}, painted{3, 97}, painted{4, 98}, painted{4, 99})
	s.ScrollPixels(lp, -14)
	check(93, -3, painted{0, 93})
	s.ScrollPixels(lp, 5)
	check(94, 2, painted{4, 98})
	s.RedrawAll(lp)
	check(94, 2, painted{0, 94}, painted{1, 95}, painted{2, 96}, painted{3, 97}, painted{4, 98}, painted{0, 93})
	// When the content shrinks, drawing scrolls to its end
	s.SetNumLines(50)
	s.Draw(lp)
	if s.Position() != 450 {
		t.Fatalf("Incorrect position after content shrank: %d", s.Position())
	}
	*p = (*p)[:0]
	// Changing the geometry snaps to a line
	s.ScrollPixels(lp, -16)
	s.SetGeometry(0, 2, 10, 6, 10)
	*p = (*p)[:0]
	s.Draw(lp)
	check(43, 0, painted{0, 43}, painted{1, 44}, painted{2, 45}, painted{3, 46}, painted{4, 47}, painted{5, 48})
}

func TestScrollerFallback(t *testing.T) {
	s, lp, p := new_test_scroller(false)
	s.Draw(lp)
	*p = (*p)[:0]
	s.ScrollPixels(lp, 9)
	if len(*p) != 0 || s.FirstLine() != 0 || s.Offset() != 0 {
		t.Fatalf("Scrolled by less than a line without smooth scrolling")
	}
	s.ScrollPixels(lp, 1)
	if len(*p) != 5 || s.FirstLine() != 1 {
		t.Fatalf("Did not scroll by a line without smooth scrolling")
	}
	// Switching to smooth scrolling keeps the line at the top
	s.ScrollPixels(lp, 15)
	s.SetSupported()
	*p = (*p)[:0]
	s.Draw(lp)
	if s.FirstLine() != 2 || s.Offset() != 0 || len(*p) != 5 {
		t.Fatalf("Incorrect position after switching to smooth scrolling: %d %d", s.FirstLine(), s.Offset())
	}
}

func TestIndicator(t *testing.T) {
	var s Indicator
	s.SetGeometry(10, 2, 10, 8, 16)
	s.SetPosition(0, 100, 10, 20)
	if !s.Visible() {
		t.Fatalf("Indicator not visible")
	}
	if start, size := s.ThumbGeometry(8); start != 0 || size != 40 {
		t.Fatalf("Incorrect thumb: %d %d", start, size)
	}
	s.SetPosition(50, 100, 10, 20)
	if start, size := s.ThumbGeometry(8); start != 20 || size != 40 {
		t.Fatalf("Incorrect thumb: %d %d", start, size)
	}
	// The thumb is at least one cell high
	s.SetPosition(100, 100, 1, 1000)
	if start, size := s.ThumbGeometry(8); start != 72 || size != 8 {
		t.Fatalf("Incorrect thumb: %d %d", start, size)
	}
	s.SetPosition(0, 100, 10, 20)
	ev := func(etype loop.MouseEventType, cell_y, pixel_y int) *loop.MouseEvent {
		e := &loop.MouseEvent{Event_type: etype, Buttons: loop.LEFT_MOUSE_BUTTON}
		e.Cell.X, e.Cell.Y, e.Pixel.Y = 10, cell_y, pixel_y
		return e
	}
	scrolled_to, paged := -1, 0
	actions := IndicatorActions{ScrollTo: func(pos int) { scrolled_to = pos }, Page: func(d int) { paged = d }}
	// The thumb is in rows 2 to 6, in pixels 32 to 112
	if consumed, changed := s.HandleMouse(ev(loop.MOUSE_PRESS, 9, 150), actions); !consumed || changed || paged != 1 {
		t.Fatalf("Clicking below the thumb did not page: %v %v %d", consumed, changed, paged)
	}
	if consumed, changed := s.HandleMouse(ev(loop.MOUSE_PRESS, 3, 50), actions); !consumed || !changed || !s.Dragging {
		t.Fatalf("Pressing on the thumb did not start a drag")
	}
	// Moving by half the free space in the track scrolls to the middle
	s.HandleMouse(ev(loop.MOUSE_MOVE, 5, 90), actions)
	if scrolled_to != 50 {
		t.Fatalf("Incorrect position for drag: %d", scrolled_to)
	}
	s.HandleMouse(ev(loop.MOUSE_MOVE, 50, 1000), actions)
	if scrolled_to != 100 {
		t.Fatalf("Incorrect position for drag: %d", scrolled_to)
	}
	if consumed, _ := s.HandleMouse(ev(loop.MOUSE_RELEASE, 5, 90), actions); !consumed || s.Dragging {
		t.Fatalf("Releasing did not stop the drag")
	}
	e := ev(loop.MOUSE_PRESS, 3, 50)
	e.Cell.X = 5
	if consumed, _ := s.HandleMouse(e, actions); consumed {
		t.Fatalf("Pressing away from the indicator was consumed")
	}
}
