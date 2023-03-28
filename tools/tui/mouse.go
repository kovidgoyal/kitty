// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"kitty/tools/tty"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
)

var _ = fmt.Print

type LinePos interface {
	LessThan(other LinePos) bool
	Equal(other LinePos) bool
}

type SelectionBoundary struct {
	line                  LinePos
	x                     int
	in_first_half_of_cell bool
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
	min_x, max_x            int
	min_y, max_y            int
	cell_width, cell_height int
}

func (self *MouseSelection) IsEmpty() bool  { return self.start.Equal(self.end) }
func (self *MouseSelection) IsActive() bool { return self.is_active }
func (self *MouseSelection) Finish()        { self.is_active = false }
func (self *MouseSelection) Clear()         { *self = MouseSelection{} }

func (ms *MouseSelection) StartNewSelection(ev *loop.MouseEvent, line LinePos, min_x, max_x, min_y, max_y, cell_width, cell_height int) {
	*ms = MouseSelection{min_x: min_x, max_x: max_x, cell_width: cell_width, cell_height: cell_height, min_y: min_y, max_y: max_y}
	ms.start.line = line
	ms.start.x = utils.Max(ms.min_x, utils.Min(ev.Cell.X, ms.max_x))
	cell_start := cell_width * ev.Cell.X
	ms.start.in_first_half_of_cell = ev.Pixel.X <= cell_start+cell_width/2
	ms.end = ms.start
	ms.is_active = true
}

func (ms *MouseSelection) Update(ev *loop.MouseEvent, line LinePos) {
	if ms.is_active {
		ms.end.x = utils.Max(ms.min_x, utils.Min(ev.Cell.X, ms.max_x))
		cell_start := ms.cell_width * ms.end.x
		ms.end.in_first_half_of_cell = ev.Pixel.X <= cell_start+ms.cell_width/2
		ms.end.line = line
	}
}

var DebugPrintln = tty.DebugPrintln

func (ms *MouseSelection) LineBounds(line_pos LinePos) (start_x, end_x int) {
	if ms.IsEmpty() {
		return -1, -1
	}
	a, b := ms.start.line, ms.end.line
	ax, bx := ms.start.x, ms.end.x
	if b.LessThan(a) {
		a, b = b, a
		ax, bx = bx, ax
	}
	if a.LessThan(line_pos) {
		if line_pos.LessThan(b) {
			return ms.min_x, ms.max_x
		} else if b.Equal(line_pos) {
			return ms.min_x, bx
		}
	} else if a.Equal(line_pos) {
		if line_pos.LessThan(b) {
			return ax, ms.max_x
		} else if b.Equal(line_pos) {
			return ax, bx
		}
	}
	return -1, -1
}

func FormatPartOfLine(sgr string, start_x, end_x, y int) string {
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
