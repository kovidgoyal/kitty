// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"sort"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/scrolling"
)

var _ = fmt.Print

// The grid is scrolled smoothly, pixel by pixel, using the smooth scrolling
// protocol, by a scrolling.Scroller whose lines are the lines of cells of
// the grid. Scrolling does not change the current item, which can be
// scrolled out of view. Moving to another item with the keyboard scrolls it
// into view.

// The id of the smooth scroll region of the grid
const grid_region_id = 1

// The number of lines of the grid the terminal keeps on each side of the
// smooth scroll region, enough for a row of tiles, so that it is restored
// when changing the direction of scrolling
const grid_region_capacity = 8

// The number of lines to scroll per wheel click, when the terminal does not report it
const grid_lines_per_click = 3

// grid_scroll is the geometry of the grid as lines of cells, its rows
// having different heights
type grid_scroll struct {
	// offsets[i] is the line at the top of row i
	offsets []int
	total   int // the number of lines in all rows
}

func new_grid_scroll(rows []grid_row) (ans grid_scroll) {
	ans.offsets = make([]int, len(rows))
	for i, r := range rows {
		ans.offsets[i] = ans.total
		ans.total += r.height()
	}
	return
}

// row_at returns the row of the grid containing the specified line and the
// line in that row, or -1 if the line is outside the grid
func (g grid_scroll) row_at(line int) (row, line_in_row int) {
	if line < 0 || line >= g.total {
		return -1, 0
	}
	row = sort.Search(len(g.offsets), func(i int) bool { return g.offsets[i] > line }) - 1
	return row, line - g.offsets[row]
}

// target_for_row returns the scroll position, in lines, at which the row
// with the specified top and bottom lines is entirely visible in a viewport
// of the specified height, scrolling as little as possible from the
// position pos, or -1 if it is already visible
func target_for_row(top, bottom, pos, viewport int) int {
	switch {
	case top < pos:
		return top
	case bottom > pos+viewport:
		return min(top, bottom-viewport)
	}
	return -1
}

// The scroll indicator {{{

// scroll_indicator_column returns the zero based column of the scroll
// indicator, the rightmost column
func scroll_indicator_column(screen_width int) int {
	return max(0, screen_width-1)
}

func (h *Handler) draw_scroll_indicator() {
	if h.in_command_mode {
		return
	}
	h.indicator.SetFromScroller(&h.scroller)
	h.indicator.Draw(h.lp)
}

// scroll_to scrolls the grid to the specified position in pixels, must be
// called inside an atomic update
func (h *Handler) scroll_to(pos int) {
	if h.scroller.ScrollTo(h.lp, pos) {
		h.draw_scroll_indicator()
	}
}

// in_grid returns whether the zero based cell is in the area of the grid,
// including the scroll indicator
func (h *Handler) in_grid(x, y int) bool {
	top := h.scroller.Top()
	return y >= top && y < top+h.scroller.Height() && x >= 0 && x <= h.scroller.Width()
}

// tile_at returns the index of the item whose tile is displayed at the
// specified zero based cell, or -1
func (h *Handler) tile_at(x, y int) int {
	if h.in_command_mode || !h.in_grid(x, y) || x >= h.scroller.Width() || x < h.grid_left {
		return -1
	}
	r, _ := h.grid.row_at(h.scroller.LineAtRow(y - h.scroller.Top()))
	if r < 0 || r >= len(h.rows) || h.rows[r].is_header() {
		return -1
	}
	c := (x - h.grid_left) / h.tiles.width()
	if items := h.rows[r].items; c < len(items) {
		return items[c]
	}
	return -1
}

// handle_grid_mouse handles dragging the thumb of the scroll indicator,
// clicking in its track and the mouse wheel over the grid. Returns true if the
// event was consumed. Must be called inside an atomic update.
func (h *Handler) handle_grid_mouse(ev *loop.MouseEvent) bool {
	if h.in_command_mode || len(h.rows) == 0 {
		h.indicator.Dragging, h.indicator.Hovering = false, false
		return false
	}
	consumed, changed := h.indicator.HandleMouse(ev, scrolling.IndicatorActions{
		ScrollTo: h.scroll_to,
		Page: func(direction int) {
			h.scroll_to(h.scroller.Position() + direction*max(1, h.scroller.Height()-1)*h.scroller.CellHeight())
		},
	})
	if changed {
		h.draw_scroll_indicator()
	}
	if on_indicator, _ := h.indicator.HitTest(ev); consumed || on_indicator {
		return true
	}
	if h.in_grid(ev.Cell.X, ev.Cell.Y) {
		if is_wheel, scrolled := h.scroller.HandleWheel(h.lp, ev, grid_lines_per_click); is_wheel {
			if scrolled {
				h.draw_scroll_indicator()
			}
			return true
		}
	}
	return false
}

// ensure_current_visible scrolls the grid so that the current item is
// visible. When scrolling up to it, the header of its section is shown too.
// Must be called inside an atomic update, after the grid is drawn.
func (h *Handler) ensure_current_visible() {
	r, _ := position_of(h.rows, h.current)
	if r < 0 {
		return
	}
	ch := h.scroller.CellHeight()
	top, bottom := h.grid.offsets[r], h.grid.offsets[r]+h.rows[r].height()
	pos := h.scroller.Position()
	if top*ch < pos && r > 0 && h.rows[r-1].is_header() {
		top = h.grid.offsets[r-1]
	}
	// Positions in pixels, so that a row partially visible is scrolled into view
	if target := target_for_row(top*ch, bottom*ch, pos, h.scroller.Height()*ch); target > -1 {
		h.scroll_to(target)
	}
}

// }}}
