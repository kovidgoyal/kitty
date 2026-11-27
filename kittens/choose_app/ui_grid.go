// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// Dimensions of a tile in cells. A tile has a one cell border, which is
// drawn only for the current tile, the icon and two lines for the name.
const (
	tile_icon_rows     = 3
	tile_name_lines    = 2
	tile_content_width = 14
	tile_width         = tile_content_width + 2
	tile_height        = tile_icon_rows + tile_name_lines + 2
)

// grid_row is either a section header or a row of tiles
type grid_row struct {
	header string
	// indices into the list of matching items
	items []int
}

func (r grid_row) is_header() bool { return r.header != "" }
func (r grid_row) height() int     { return utils.IfElse(r.is_header(), 1, tile_height) }

func num_grid_columns(width int) int {
	return max(1, width/tile_width)
}

// layout_grid arranges the matching items into rows. With sections, the
// recommended items and the others are placed in separate sections.
func layout_grid(items []*item, with_sections bool, ncols int) (rows []grid_row) {
	add_tiles := func(start, end int) {
		for i := start; i < end; i += ncols {
			r := grid_row{}
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
