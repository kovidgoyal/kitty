// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// tile_geometry is the size of a tile in cells. A tile has a one cell
// border, which is drawn only for the current tile, the icon and the lines
// for the name.
type tile_geometry struct {
	icon_rows, name_lines, content_width int
}

func (t tile_geometry) width() int  { return t.content_width + 2 }
func (t tile_geometry) height() int { return t.icon_rows + t.name_lines + 2 }

const (
	default_icon_rows  = 3
	default_tile_width = 16
	// The largest scale supported by the text sizing protocol, used to draw
	// placeholders for missing icons
	max_icon_rows = 7
	// Narrower tiles cannot show useful names
	min_tile_width = 8
	max_tile_width = 64
)

func new_tile_geometry(icon_rows, width int) tile_geometry {
	return tile_geometry{icon_rows: icon_rows, name_lines: 2, content_width: width - 2}
}

var default_tile_geometry = new_tile_geometry(default_icon_rows, default_tile_width)

// grid_row is either a section header or a row of tiles
type grid_row struct {
	header string
	// indices into the list of matching items
	items []int
	// the height of a row of tiles
	tile_height int
}

func (r grid_row) is_header() bool { return r.header != "" }
func (r grid_row) height() int     { return utils.IfElse(r.is_header(), 1, r.tile_height) }

func num_grid_columns(width int, tiles tile_geometry) int {
	return max(1, width/tiles.width())
}

// layout_grid arranges the matching items into rows. With sections, the
// recommended items and the others are placed in separate sections.
func layout_grid(items []*item, with_sections bool, ncols int, tiles tile_geometry) (rows []grid_row) {
	add_tiles := func(start, end int) {
		for i := start; i < end; i += ncols {
			r := grid_row{tile_height: tiles.height()}
			for j := i; j < min(end, i+ncols); j++ {
				r.items = append(r.items, j)
			}
			rows = append(rows, r)
		}
	}
	if !with_sections {
		add_tiles(0, len(items))
		return
	}
	num_recommended := 0
	for num_recommended < len(items) && items[num_recommended].recommended {
		num_recommended++
	}
	if num_recommended > 0 {
		rows = append(rows, grid_row{header: "Recommended"})
		add_tiles(0, num_recommended)
	}
	if num_recommended < len(items) {
		rows = append(rows, grid_row{header: utils.IfElse(num_recommended > 0, "Other applications", "All applications")})
		add_tiles(num_recommended, len(items))
	}
	return
}

// position_of returns the row and column of the item with the specified index
func position_of(rows []grid_row, idx int) (row, col int) {
	for r, gr := range rows {
		for c, i := range gr.items {
			if i == idx {
				return r, c
			}
		}
	}
	return -1, -1
}

// tile_row_from returns the index of the first row of tiles at or after
// (delta > 0) or at or before (delta < 0) the specified row, or -1
func tile_row_from(rows []grid_row, r, delta int) int {
	for ; r >= 0 && r < len(rows); r += delta {
		if !rows[r].is_header() {
			return r
		}
	}
	return -1
}

// move_vertically returns the index of the item amt rows of tiles below (or
// above if negative) the item idx, keeping the column if possible. Stops at
// the first or last row.
func move_vertically(rows []grid_row, idx, amt int) int {
	r, c := position_of(rows, idx)
	if r < 0 {
		return idx
	}
	delta := utils.IfElse(amt > 0, 1, -1)
	for range max(amt, -amt) {
		next := tile_row_from(rows, r+delta, delta)
		if next < 0 {
			break
		}
		r = next
	}
	items := rows[r].items
	return items[min(c, len(items)-1)]
}
