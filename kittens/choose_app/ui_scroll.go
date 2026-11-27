// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"math"

	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// grid_scroll is the scroll geometry of the grid, whose rows have different
// heights. The grid is scrolled by whole rows, while the thumb of the scroll
// indicator is positioned with sub-cell precision.
type grid_scroll struct {
	// offsets[i] is the distance in cells from the top of the grid to row i
	offsets  []int
	total    int // the height of all rows
	viewport int // the height in which rows are displayed
}

func new_grid_scroll(rows []grid_row, viewport int) (ans grid_scroll) {
	ans.offsets = make([]int, len(rows))
	for i, r := range rows {
		ans.offsets[i] = ans.total
		ans.total += r.height()
	}
	ans.viewport = viewport
	return
}

func (g grid_scroll) scrollable() bool { return g.viewport > 0 && g.total > g.viewport }

// max_first_row returns the first row to display when scrolled to the bottom:
// the first row from which all remaining rows fit
func (g grid_scroll) max_first_row() int {
	for r, off := range g.offsets {
		if g.total-off <= g.viewport {
			return r
		}
	}
	return max(0, len(g.offsets)-1)
}

func (g grid_scroll) clamp(first_row int) int {
	return max(0, min(first_row, g.max_first_row()))
}

// thumb returns the position and size of the thumb in units of
// 1/units_per_cell of a cell from the top of the track. size is zero when all
// rows fit. The thumb is at least one cell high, so that it is easy to grab.
func (g grid_scroll) thumb(first_row, units_per_cell int) (start, size int) {
	if !g.scrollable() {
		return 0, 0
	}
	track := g.viewport * units_per_cell
	size = max(units_per_cell, track*g.viewport/g.total)
	if max_off := g.offsets[g.max_first_row()]; max_off > 0 {
		frac := float64(g.offsets[g.clamp(first_row)]) / float64(max_off)
		start = int(frac*float64(track-size) + 0.5)
	}
	return
}

// row_for_thumb returns the first row to display for the thumb to be at
// top, in units of 1/units_per_cell of a cell from the top of the track
func (g grid_scroll) row_for_thumb(top float64, units_per_cell int) int {
	_, size := g.thumb(0, units_per_cell)
	track := g.viewport * units_per_cell
	if track <= size {
		return 0
	}
	last := g.max_first_row()
	target := max(0, min(1, top/float64(track-size))) * float64(g.offsets[last])
	best := 0
	for r := 1; r <= last; r++ {
		if math.Abs(float64(g.offsets[r])-target) < math.Abs(float64(g.offsets[best])-target) {
			best = r
		}
	}
	return best
}

// row_for_offset returns the row whose top is closest to the specified
// distance in cells from the top of the grid, that can be the first row displayed
func (g grid_scroll) row_for_offset(offset int) int {
	last := g.max_first_row()
	best := 0
	for r := 1; r <= last; r++ {
		if abs(g.offsets[r]-offset) < abs(g.offsets[best]-offset) {
			best = r
		}
	}
	return best
}

func abs(x int) int { return max(x, -x) }

// The scroll indicator {{{

// The SGR colors of the thumb when drawn with block characters, the same as
// the palette colors used for the thumb image
const (
	thumb_block_color         = "36"
	thumb_block_hovered_color = "96"
)

type scroll_indicator struct {
	thumb          *graphics.ScrollThumb
	dragging       bool
	hovering       bool
	grab_offset    float64 // in pixels from the top of the thumb
	visible        bool
	x, y           int // zero based cell position of the top of the track
	units_per_cell int
	start, size    int // the thumb in units of 1/units_per_cell of a cell
	cell_height    int
	geometry       grid_scroll
}

func (h *Handler) scroll_geometry() grid_scroll {
	return new_grid_scroll(h.rows, h.grid_height())
}

func (h *Handler) thumb_units_per_cell() int {
	if h.scroll.thumb != nil && h.scroll.thumb.Supported {
		return int(h.screen_size.CellHeight)
	}
	return graphics.EighthsPerCell
}

// scroll_indicator_column returns the zero based column of the scroll
// indicator. It is not in the rightmost columns, as when the window has
// scrollback, kitty does not report mouse events over its own scrollbar, at
// the right edge of the window, to programs, even when the scrollbar is not
// shown, which would prevent hovering over and dragging the thumb.
func scroll_indicator_column(screen_width int) int {
	return max(0, screen_width-3)
}

// draw_scroll_indicator draws the scroll bar to the right of the grid
func (h *Handler) draw_scroll_indicator(y int) {
	s := &h.scroll
	g := h.scroll_geometry()
	units := h.thumb_units_per_cell()
	start, size := g.thumb(h.first_row, units)
	s.visible = size > 0
	s.x, s.y, s.units_per_cell, s.start, s.size, s.cell_height = scroll_indicator_column(int(h.screen_size.WidthCells)), y, units, start, size, int(h.screen_size.CellHeight)
	s.geometry = g
	if !s.visible {
		s.dragging, s.hovering = false, false
		if s.thumb != nil {
			s.thumb.Hide(h.lp)
		}
		return
	}
	hovered := s.dragging || s.hovering
	image := s.thumb != nil && s.thumb.Supported
	for row := range g.viewport {
		h.lp.MoveCursorTo(s.x+1, y+row+1)
		if image {
			h.lp.QueueWriteString(h.styled(dim_style, "│"))
		} else {
			h.lp.QueueWriteString(graphics.ThumbBlockCell(row, start, start+size, utils.IfElse(hovered, thumb_block_hovered_color, thumb_block_color)))
		}
	}
	if image {
		key := graphics.ScrollThumbKey{Width: int(h.screen_size.CellWidth), Height: size, Hovered: hovered}
		s.thumb.Draw(h.lp, key, s.x, y, start, int(h.screen_size.CellHeight))
	}
}

// hit_test returns whether the mouse is over the scroll indicator and if so,
// whether it is over the thumb (0), or above (-1) or below (1) it. The
// column to the left of the indicator also counts, as a single column is
// a small target.
func (s *scroll_indicator) hit_test(ev *loop.MouseEvent) (on_indicator bool, where int) {
	if !s.visible || ev.Cell.X < s.x-1 || ev.Cell.X > s.x || ev.Cell.Y < s.y || ev.Cell.Y >= s.y+s.geometry.viewport {
		return false, 0
	}
	px_per_unit := float64(s.cell_height) / float64(s.units_per_cell)
	top, height := float64(s.start)*px_per_unit, float64(s.size)*px_per_unit
	y := float64(ev.Pixel.Y - s.y*s.cell_height)
	switch {
	case y < top:
		return true, -1
	case y >= top+height:
		return true, 1
	}
	return true, 0
}

// set_first_row scrolls the grid, moving the current item into view if
// it is scrolled out of view
func (h *Handler) set_first_row(r int) {
	g := h.scroll_geometry()
	h.first_row = g.clamp(r)
	cr, col := position_of(h.rows, h.current)
	if cr < 0 {
		return
	}
	top, bottom := g.offsets[h.first_row], g.offsets[h.first_row]+g.viewport
	visible := func(r int) bool { return g.offsets[r] >= top && g.offsets[r]+h.rows[r].height() <= bottom }
	if visible(cr) {
		return
	}
	pick := -1
	if g.offsets[cr] < top {
		for r := h.first_row; r < len(h.rows); r++ {
			if !h.rows[r].is_header() && visible(r) {
				pick = r
				break
			}
		}
	} else {
		for r := len(h.rows) - 1; r >= h.first_row; r-- {
			if !h.rows[r].is_header() && visible(r) {
				pick = r
				break
			}
		}
	}
	if pick > -1 {
		items := h.rows[pick].items
		h.current = items[min(col, len(items)-1)]
	}
}

// handle_scroll_mouse handles dragging the thumb, clicking in the track of
// the scroll indicator and the mouse wheel. Returns true if the event was
// consumed and whether a redraw is needed.
func (h *Handler) handle_scroll_mouse(ev *loop.MouseEvent) (consumed, redraw bool) {
	s := &h.scroll
	if h.in_command_mode || len(h.rows) == 0 {
		s.dragging, s.hovering = false, false
		return false, false
	}
	g := s.geometry
	in_grid := ev.Cell.Y >= s.y && ev.Cell.Y < s.y+g.viewport
	if ev.Event_type == loop.MOUSE_PRESS && ev.Buttons&(loop.MOUSE_WHEEL_UP|loop.MOUSE_WHEEL_DOWN) != 0 {
		if !in_grid || !g.scrollable() {
			return false, false
		}
		delta := 1
		if ev.Buttons&loop.MOUSE_WHEEL_UP != 0 {
			delta = -1
		}
		h.set_first_row(h.first_row + delta)
		return true, true
	}
	left_held := ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0
	on_indicator, where := s.hit_test(ev)
	was_hovering, was_dragging := s.hovering, s.dragging
	px_per_unit := float64(s.cell_height) / float64(max(1, s.units_per_cell))
	switch ev.Event_type {
	case loop.MOUSE_PRESS:
		if left_held && on_indicator {
			consumed = true
			if where == 0 {
				s.dragging = true
				s.grab_offset = float64(ev.Pixel.Y-s.y*s.cell_height) - float64(s.start)*px_per_unit
			} else {
				// Page up or down
				h.set_first_row(g.row_for_offset(g.offsets[h.first_row] + where*max(1, g.viewport-1)))
				redraw = true
			}
		}
	case loop.MOUSE_MOVE:
		if s.dragging {
			if left_held {
				consumed, redraw = true, true
				top := (float64(ev.Pixel.Y-s.y*s.cell_height) - s.grab_offset) / px_per_unit
				h.set_first_row(g.row_for_thumb(top, s.units_per_cell))
			} else {
				// The release was not reported, for instance, because it
				// happened outside the window
				s.dragging = false
			}
		}
	case loop.MOUSE_RELEASE:
		if s.dragging && ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0 {
			consumed = true
			s.dragging = false
		}
	}
	s.hovering = ev.Event_type != loop.MOUSE_LEAVE && on_indicator && where == 0
	if was_hovering != s.hovering || was_dragging != s.dragging {
		redraw = true
	}
	return consumed || on_indicator, redraw
}

// }}}
