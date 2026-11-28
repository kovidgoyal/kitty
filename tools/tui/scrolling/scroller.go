// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

// Package scrolling implements smooth, pixel by pixel, scrolling of lines of
// content in a rectangle of the screen, using the smooth scrolling protocol,
// see docs/smooth-scrolling-protocol.rst, and a scroll indicator showing the
// position in the content. In terminals that do not support the protocol,
// the content is scrolled by whole lines.
package scrolling

import (
	"fmt"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print

// Scroller displays lines of content, each one cell high, in a rectangle of
// the screen and scrolls them by any number of pixels, drawing only the lines
// that move into the rectangle. All methods that draw must be called inside
// an atomic update, so that the scrolling and the drawing of the lines that
// move into the rectangle are rendered together.
type Scroller struct {
	// The id of the smooth scroll region, must be non-zero and different
	// from the ids of the other regions used by the program
	Id uint32
	// The number of rows the terminal keeps on each side of the region,
	// after they move out of it, see the protocol docs. Zero means one.
	Capacity uint32
	// Paint draws the line of content with the specified index in the
	// specified row of the rectangle, relative to its top. The index can be
	// outside the content, the row must then be drawn blank. Paint must
	// draw the whole row, but nothing outside it, and must not cause the
	// screen to scroll.
	Paint func(row, line int)

	// Whether the terminal supports the smooth scrolling protocol
	supported bool
	// The rectangle, in zero based cells, and the height of a cell in pixels
	left, top, width, height, cell_height int
	num_lines                             int
	// Whether the content was drawn and, for terminals that support smooth
	// scrolling, the region defined for the current rectangle
	drawn bool
	// The line of content in the first row of the rectangle and the offset
	// of the region in pixels, as described in the protocol docs
	first_line, offset int
	// Scroll amounts are accumulated in fractions of a pixel
	pending float64
	// The position in pixels used when the terminal does not support smooth scrolling
	fallback_pos int
}

// SetSupported must be called when the terminal is found to support smooth
// scrolling, see loop.QuerySmoothScrolling(). Call Draw() afterwards.
func (s *Scroller) SetSupported() {
	if s.supported {
		return
	}
	pos := s.fallback_pos
	s.supported, s.drawn = true, false
	s.first_line, s.offset = pos/max(1, s.cell_height), 0
}

func (s *Scroller) Supported() bool { return s.supported }

// SetGeometry sets the rectangle, in zero based cells, in which the content
// is displayed and the height of a cell in pixels. Call Draw() afterwards.
func (s *Scroller) SetGeometry(left, top, width, height, cell_height int) {
	cell_height = max(1, cell_height)
	if s.left != left || s.top != top || s.width != width || s.height != height || s.cell_height != cell_height {
		pos := s.Position()
		if s.cell_height > 0 && s.cell_height != cell_height {
			// Keep the same line at the top
			pos = pos * cell_height / s.cell_height
		}
		s.left, s.top, s.width, s.height, s.cell_height = left, top, width, height, cell_height
		s.set_position_snapped(pos)
		s.drawn = false
	}
}

// SetNumLines sets the number of lines of content. Call Draw() afterwards.
func (s *Scroller) SetNumLines(n int) { s.num_lines = max(0, n) }

// SetPosition sets the scroll position, snapped to the start of the
// nearest line, without scrolling, for instance, when the content is
// replaced. Draw() then draws all lines and defines the region again.
func (s *Scroller) SetPosition(pos int) {
	s.set_position_snapped(pos)
	s.drawn = false
}

// Invalidate must be called when the terminal removes the smooth scroll
// region, for instance, when it is resized, or when the rectangle is used to
// display something else. Draw() then draws all lines and defines the
// region again.
func (s *Scroller) Invalidate() { s.drawn = false }

// Remove removes the smooth scroll region, for instance, before displaying
// something else in its rectangle. Draw() draws the content again.
func (s *Scroller) Remove(lp *loop.Loop) {
	if s.supported && s.drawn {
		lp.RemoveSmoothScrollRegion(s.Id)
	}
	s.drawn = false
}

func (s *Scroller) Left() int       { return s.left }
func (s *Scroller) Top() int        { return s.top }
func (s *Scroller) Width() int      { return s.width }
func (s *Scroller) Height() int     { return s.height }
func (s *Scroller) CellHeight() int { return s.cell_height }
func (s *Scroller) NumLines() int   { return s.num_lines }

// Whether there is more content than fits in the rectangle
func (s *Scroller) Scrollable() bool { return s.height > 0 && s.num_lines > s.height }

// Position returns the scroll position, the distance in pixels from the top
// of the content to the top of the rectangle
func (s *Scroller) Position() int {
	if !s.supported {
		return s.fallback_pos
	}
	return s.first_line*s.cell_height - s.offset
}

// MaxPosition returns the scroll position at which the last line of content
// is at the bottom of the rectangle
func (s *Scroller) MaxPosition() int { return s.MaxFirstLine() * s.cell_height }

// MaxFirstLine returns the line at the top of the rectangle, when scrolled to the end
func (s *Scroller) MaxFirstLine() int { return max(0, s.num_lines-s.height) }

// FirstLine returns the line of content in the first row of the rectangle.
// When the content is shifted by a fraction of a line, part of the line
// before it (when Offset() is positive) or after the last row (when Offset()
// is negative) is visible as well.
func (s *Scroller) FirstLine() int {
	if !s.supported {
		return s.fallback_pos / max(1, s.cell_height)
	}
	return s.first_line
}

// Offset returns the offset of the region, as described in the protocol docs
func (s *Scroller) Offset() int {
	if !s.supported {
		return 0
	}
	return s.offset
}

// LineAtRow returns the line of content in the specified row of the
// rectangle, relative to its top. Mouse events are reported for the row
// drawn under the mouse pointer, so this is the line under the mouse for an
// event in this row.
func (s *Scroller) LineAtRow(row int) int { return s.FirstLine() + row }

func (s *Scroller) clamp(pos int) int { return max(0, min(pos, s.MaxPosition())) }

// set_position_snapped sets the position to the start of the line nearest to pos
func (s *Scroller) set_position_snapped(pos int) {
	h := max(1, s.cell_height)
	pos = s.clamp(pos)
	s.first_line, s.offset = (pos+h/2)/h, 0
	s.first_line = min(s.first_line, s.MaxFirstLine())
	s.fallback_pos = s.first_line * h
	s.pending = 0
}

func (s *Scroller) paint_all() {
	for row := range s.height {
		s.Paint(row, s.FirstLine()+row)
	}
}

// Draw draws all lines and, when the region needs to be defined, for
// instance, after the geometry changed, defines it, snapping the position to
// the start of a line, as the offset of a newly defined region is zero.
// Otherwise the current position, limited to the content, is kept.
func (s *Scroller) Draw(lp *loop.Loop) {
	if s.height < 1 || s.width < 1 || s.Paint == nil {
		return
	}
	switch {
	case !s.drawn:
		s.set_position_snapped(s.Position())
		s.paint_all()
		if s.supported {
			lp.DefineSmoothScrollRegion(loop.SmoothScrollRegion{
				Id: s.Id, X: uint32(s.left + 1), Y: uint32(s.top + 1),
				Width: uint32(s.width), Height: uint32(s.height), Capacity: s.Capacity,
				PrivateOverflow: true,
			})
		}
		s.drawn = true
	case s.Position() != s.clamp(s.Position()):
		// The content shrank
		if s.supported {
			s.scroll_pixels(lp, s.clamp(s.Position())-s.Position())
		} else {
			s.fallback_pos = s.clamp(s.fallback_pos)
		}
		s.RedrawAll(lp)
	default:
		s.RedrawAll(lp)
	}
}

// RedrawAll draws all visible lines again, including the partially visible
// line at the edge of the rectangle, keeping the current position. Use it
// when the content of the lines changed. Draw() must have been called before.
func (s *Scroller) RedrawAll(lp *loop.Loop) {
	if !s.drawn || s.Paint == nil {
		return
	}
	s.paint_all()
	if !s.supported || s.offset == 0 {
		return
	}
	// The partially visible line is not in the rectangle, scroll it into
	// the rectangle, draw it and scroll it out again, see the protocol docs
	h, r := s.cell_height, s.offset
	if r > 0 {
		lp.SmoothScroll(s.Id, -(h - r))
		s.Paint(0, s.first_line-1)
		lp.SmoothScroll(s.Id, h-r)
	} else {
		lp.SmoothScroll(s.Id, h+r)
		s.Paint(s.height-1, s.first_line+s.height)
		lp.SmoothScroll(s.Id, -(h + r))
	}
}

// ScrollLines scrolls by the specified number of lines, which can be
// fractional, returning false if nothing was scrolled
func (s *Scroller) ScrollLines(lp *loop.Loop, lines float64) bool {
	if !s.drawn {
		return false
	}
	s.pending += lines * float64(s.cell_height)
	d := int(s.pending)
	s.pending -= float64(d)
	if d == 0 {
		return false
	}
	if !s.ScrollPixels(lp, d) {
		// At the start or end of the content
		s.pending = 0
		return false
	}
	return true
}

// ScrollToLine scrolls so that the specified line is at the top of the
// rectangle, or as close to it as possible, returning false if nothing was
// scrolled
func (s *Scroller) ScrollToLine(lp *loop.Loop, line int) bool {
	return s.ScrollTo(lp, line*s.cell_height)
}

// ScrollTo scrolls to the specified position, limited to the content,
// returning false if nothing was scrolled
func (s *Scroller) ScrollTo(lp *loop.Loop, pos int) bool {
	return s.ScrollPixels(lp, s.clamp(pos)-s.Position())
}

// ScrollPixels scrolls by the specified number of pixels, limited to the
// content, returning false if nothing was scrolled. Positive values scroll
// towards the end of the content.
func (s *Scroller) ScrollPixels(lp *loop.Loop, d int) bool {
	if !s.drawn || s.height < 1 {
		return false
	}
	pos := s.Position()
	d = s.clamp(pos+d) - pos
	if d == 0 {
		return false
	}
	if !s.supported {
		before := s.fallback_pos / s.cell_height
		s.fallback_pos += d
		if s.fallback_pos/s.cell_height != before {
			s.paint_all()
		}
		return true
	}
	s.scroll_pixels(lp, d)
	return true
}

// RowShift performs the calculation from the protocol docs: given the
// offset of a region, the height of a cell and the amount to scroll by, it
// returns the number of rows by which the cells move, positive values
// meaning towards the top, and the new offset
func RowShift(offset, cell_height, d int) (shift, new_offset int) {
	h := cell_height
	moved := offset - d
	if d > 0 {
		if moved < 0 {
			shift = (-moved + h - 1) / h
		}
	} else if moved > 0 {
		shift = -((moved + h - 1) / h)
	}
	return shift, moved + shift*h
}

func (s *Scroller) scroll_pixels(lp *loop.Loop, d int) {
	shift, offset := RowShift(s.offset, s.cell_height, d)
	s.offset = offset
	s.first_line += shift
	lp.SmoothScroll(s.Id, d)
	n := min(max(shift, -shift), s.height)
	start := 0
	if shift > 0 {
		start = s.height - n
	}
	for row := start; row < start+n; row++ {
		s.Paint(row, s.first_line+row)
	}
}

// HandleWheel scrolls in response to mouse wheel events, both detailed wheel
// events, which can be in pixels, and wheel button presses in terminals that
// do not support them. default_lines_per_click is used when the terminal
// does not report how many lines to scroll per wheel click. Returns whether
// the event is a wheel event and whether anything was scrolled.
func (s *Scroller) HandleWheel(lp *loop.Loop, ev *loop.MouseEvent, default_lines_per_click float64) (is_wheel, scrolled bool) {
	switch {
	case ev.Event_type == loop.MOUSE_WHEEL:
		_, lines := ev.Wheel.Lines(s.cell_height, default_lines_per_click)
		return true, s.ScrollLines(lp, lines)
	case ev.Event_type == loop.MOUSE_PRESS && ev.Buttons&loop.MOUSE_WHEEL_UP != 0:
		return true, s.ScrollLines(lp, -default_lines_per_click)
	case ev.Event_type == loop.MOUSE_PRESS && ev.Buttons&loop.MOUSE_WHEEL_DOWN != 0:
		return true, s.ScrollLines(lp, default_lines_per_click)
	case ev.Event_type == loop.MOUSE_PRESS && ev.Buttons&(loop.MOUSE_WHEEL_LEFT|loop.MOUSE_WHEEL_RIGHT) != 0:
		return true, false
	}
	return false, false
}
