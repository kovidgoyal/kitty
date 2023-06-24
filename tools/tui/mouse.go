// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"time"

	"kitty/tools/tui/loop"
	"kitty/tools/utils"
)

var _ = fmt.Print

type LinePos interface {
	LessThan(other LinePos) bool
	Equal(other LinePos) bool
	MinX() int
	MaxX() int
}

type SelectionBoundary struct {
	line                  LinePos
	x                     int
	in_first_half_of_cell bool
}

func (self *SelectionBoundary) LessThan(other *SelectionBoundary) bool {
	if self.line.LessThan(other.line) {
		return true
	}
	if !self.line.Equal(other.line) {
		return false
	}
	if self.x == other.x {
		return !self.in_first_half_of_cell && other.in_first_half_of_cell
	}
	return self.x < other.x
}

func (self *SelectionBoundary) Equal(other SelectionBoundary) bool {
	if self.x != other.x || self.in_first_half_of_cell != other.in_first_half_of_cell {
		return false
	}
	if self.line == nil {
		return other.line == nil
	}
	return self.line.Equal(other.line)
}

type MouseSelection struct {
	start, end              SelectionBoundary
	is_active               bool
	min_y, max_y            int
	cell_width, cell_height int
	drag_scroll             struct {
		timer_id    loop.IdType
		pixel_gap   int
		mouse_event loop.MouseEvent
	}
}

func (self *MouseSelection) IsEmpty() bool  { return self.start.Equal(self.end) }
func (self *MouseSelection) IsActive() bool { return self.is_active }
func (self *MouseSelection) Finish()        { self.is_active = false }
func (self *MouseSelection) Clear()         { *self = MouseSelection{} }

func (ms *MouseSelection) StartNewSelection(ev *loop.MouseEvent, line LinePos, min_y, max_y, cell_width, cell_height int) {
	*ms = MouseSelection{cell_width: cell_width, cell_height: cell_height, min_y: min_y, max_y: max_y}
	ms.start.line = line
	ms.start.x = utils.Max(line.MinX(), utils.Min(ev.Cell.X, line.MaxX()))
	cell_start := cell_width * ev.Cell.X
	ms.start.in_first_half_of_cell = ev.Pixel.X <= cell_start+cell_width/2
	ms.end = ms.start
	ms.is_active = true
}

func (ms *MouseSelection) Update(ev *loop.MouseEvent, line LinePos) {
	ms.drag_scroll.timer_id = 0
	if ms.is_active {
		ms.end.x = utils.Max(line.MinX(), utils.Min(ev.Cell.X, line.MaxX()))
		cell_start := ms.cell_width * ms.end.x
		ms.end.in_first_half_of_cell = ev.Pixel.X <= cell_start+ms.cell_width/2
		ms.end.line = line
	}
}

func (ms *MouseSelection) LineBounds(line_pos LinePos) (start_x, end_x int) {
	if ms.IsEmpty() {
		return -1, -1
	}
	a, b := &ms.start, &ms.end
	if b.LessThan(a) {
		a, b = b, a
	}

	adjust_end := func(x int, b *SelectionBoundary) (int, int) {
		if b.in_first_half_of_cell {
			if b.x > x {
				return x, b.x - 1
			}
			return -1, -1
		}
		return x, b.x
	}

	adjust_start := func(a *SelectionBoundary, x int) (int, int) {
		if a.in_first_half_of_cell {
			return a.x, x
		}
		if x > a.x {
			return a.x + 1, x
		}
		return -1, -1
	}

	adjust_both := func(a, b *SelectionBoundary) (int, int) {
		if a.in_first_half_of_cell {
			return adjust_end(a.x, b)
		} else {
			if b.in_first_half_of_cell {
				s, e := a.x+1, b.x-1
				if e <= s {
					return -1, -1
				}
				return s, e
			} else {
				return adjust_start(a, b.x)
			}
		}
	}

	if a.line.LessThan(line_pos) {
		if line_pos.LessThan(b.line) {
			return line_pos.MinX(), line_pos.MaxX()
		} else if b.line.Equal(line_pos) {
			return adjust_end(line_pos.MinX(), b)
		}
	} else if a.line.Equal(line_pos) {
		if line_pos.LessThan(b.line) {
			return adjust_start(a, line_pos.MaxX())
		} else if b.line.Equal(line_pos) {
			return adjust_both(a, b)
		}
	}
	return -1, -1
}

func FormatPartOfLine(sgr string, start_x, end_x, y int) string { // uses zero based indices
	// DECCARA used to set formatting in specified region using zero based indexing
	return fmt.Sprintf("\x1b[%d;%d;%d;%d;%s$r", y+1, start_x+1, y+1, end_x+1, sgr)
}

func (ms *MouseSelection) LineFormatSuffix(line_pos LinePos, sgr string, y int) string {
	s, e := ms.LineBounds(line_pos)
	if s > -1 {
		return FormatPartOfLine(sgr, s, e, y)
	}
	return ""
}

func (ms *MouseSelection) StartLine() LinePos {
	return ms.start.line
}

func (ms *MouseSelection) EndLine() LinePos {
	return ms.end.line
}

func (ms *MouseSelection) OutOfVerticalBounds(ev *loop.MouseEvent) bool {
	return ev.Pixel.Y < ms.min_y*ms.cell_height || ev.Pixel.Y > (ms.max_y+1)*ms.cell_height
}

func (ms *MouseSelection) DragScrollTick(timer_id loop.IdType, lp *loop.Loop, callback loop.TimerCallback, do_scroll func(int, *loop.MouseEvent) error) error {
	if !ms.is_active || ms.drag_scroll.timer_id != timer_id || ms.drag_scroll.pixel_gap == 0 {
		return nil
	}
	amt := 1
	if ms.drag_scroll.pixel_gap < 0 {
		amt *= -1
	}
	err := do_scroll(amt, &ms.drag_scroll.mouse_event)
	if err == nil {
		ms.drag_scroll.timer_id, _ = lp.AddTimer(50*time.Millisecond, false, callback)
	}
	return err
}

func (ms *MouseSelection) DragScroll(ev *loop.MouseEvent, lp *loop.Loop, callback loop.TimerCallback) {
	if !ms.is_active {
		return
	}
	upper := ms.min_y * ms.cell_height
	lower := (ms.max_y + 1) * ms.cell_height
	if ev.Pixel.Y < upper {
		ms.drag_scroll.pixel_gap = ev.Pixel.Y - upper
	} else if ev.Pixel.Y > lower {
		ms.drag_scroll.pixel_gap = ev.Pixel.Y - lower
	}
	if ms.drag_scroll.timer_id == 0 && ms.drag_scroll.pixel_gap != 0 {
		ms.drag_scroll.timer_id, _ = lp.AddTimer(50*time.Millisecond, false, callback)
	}
	ms.drag_scroll.mouse_event = *ev
}
