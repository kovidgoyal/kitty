// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package mouse_demo

import (
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

// A box with text describing the kitten, scrolled smoothly, pixel by pixel, in
// response to wheel events, using the smooth scrolling protocol, see
// docs/smooth-scrolling-protocol.rst. Terminals that do not support the
// protocol are detected with a query, the text then scrolls by whole lines.

const (
	text_region_id       = 1
	max_text_box_width   = 90
	max_text_col_width   = 72
	text_region_capacity = 3
	lines_per_click      = 3 // used when the terminal does not send its multiplier
)

const description = `The kitty mouse features demo

This kitten demonstrates the mouse related features of the kitty terminal protocol extensions: detailed reporting of mouse events, including high resolution scroll wheel and touchpad events, mouse pointer shapes, drag and drop and smooth scrolling.

Things to try:

• Move the mouse or click anywhere to see the reported mouse events at the top.
• Hover the mouse over the names of the pointer shapes to see each shape.
• Drag files or text from another program and drop them in the drop box.
• Scroll this text with a mouse wheel or a touchpad. With a touchpad or a high resolution wheel it scrolls smoothly, pixel by pixel, following your fingers, using the smooth scrolling protocol. The bar on the right edge of this box shows the position in the text.
• Press Esc or Ctrl+C to quit.`

const filler_paragraph = `Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.`

const num_filler_paragraphs = 12

type text_line struct {
	text, sgr string
}

type text_area struct {
	// Whether the terminal supports the smooth scrolling protocol
	supported bool
	// The wrapped lines of text and the width they were wrapped for
	lines        []text_line
	wrapped_for  int
	cell_height  int
	screen_lines int
	// The box, in zero based cells, with its interior being the smooth scroll region
	visible                                          bool
	box_left, box_top, box_width, box_height         int
	inner_left, inner_top, inner_width, inner_height int
	text_left                                        int
	// The line of text in the first row of the interior and the offset of the
	// region in pixels, see the smooth scrolling protocol docs
	first_line, offset int
	// Scroll amounts are accumulated in fractions of a pixel
	pending_pixels float64
	// The position in pixels used when the terminal does not support smooth scrolling
	fallback_pos int
}

func (t *text_area) wrap(width int) {
	if t.wrapped_for == width && t.lines != nil {
		return
	}
	t.wrapped_for = width
	t.lines = t.lines[:0]
	opts := style.WrapOptions{Trim_whitespace: true}
	for i, para := range strings.Split(description, "\n\n") {
		if i > 0 {
			t.lines = append(t.lines, text_line{})
		}
		sgr := ""
		if i == 0 {
			sgr = "\x1b[1m"
		}
		for _, line := range strings.Split(para, "\n") {
			indent := ""
			if strings.HasPrefix(line, "• ") {
				indent = "  "
			}
			for j, wl := range style.WrapTextAsLines(line, width-len(indent), opts) {
				if j > 0 {
					wl = indent + wl
				}
				t.lines = append(t.lines, text_line{text: wl, sgr: sgr})
			}
		}
	}
	// A blank line followed by filler text
	t.lines = append(t.lines, text_line{})
	for i := range num_filler_paragraphs {
		if i > 0 {
			t.lines = append(t.lines, text_line{})
		}
		for _, wl := range style.WrapTextAsLines(filler_paragraph, width, opts) {
			t.lines = append(t.lines, text_line{text: wl, sgr: "\x1b[2m"})
		}
	}
}

// set_supported is called when the terminal is found to support smooth scrolling
func (t *text_area) set_supported() {
	if t.supported {
		return
	}
	pos := t.fallback_pos
	t.supported = true
	t.first_line = pos / t.cell_height
	t.offset = t.first_line*t.cell_height - pos
}

// The scroll position in pixels and its maximum
func (t *text_area) position() int {
	if !t.supported {
		return t.fallback_pos
	}
	return t.first_line*t.cell_height - t.offset
}

func (t *text_area) max_position() int {
	return max(0, len(t.lines)-t.inner_height) * t.cell_height
}

// layout positions the box in the rows [top, screen_height) of the screen
func (t *text_area) layout(top int, sz loop.ScreenSize) {
	sw, sh := int(sz.WidthCells), int(sz.HeightCells)
	t.cell_height = max(1, int(sz.CellHeight))
	t.box_width = min(sw, max_text_box_width)
	t.box_height = sh - top
	t.visible = t.box_height >= 3 && t.box_width >= 8
	if !t.visible {
		return
	}
	t.box_left = (sw - t.box_width) / 2
	t.box_top = top
	t.inner_left, t.inner_top = t.box_left+1, t.box_top+1
	t.inner_width, t.inner_height = t.box_width-2, t.box_height-2
	text_width := max(1, min(t.inner_width-4, max_text_col_width))
	t.text_left = t.inner_left + (t.inner_width-text_width)/2
	pos := t.position()
	t.wrap(text_width)
	// Start the region at a whole line, its offset is zero when it is defined
	pos = max(0, min(pos, t.max_position()))
	t.first_line = (pos + t.cell_height/2) / t.cell_height
	t.offset = 0
	t.fallback_pos = t.first_line * t.cell_height
}

func (t *text_area) paint_row(lp *loop.Loop, row int) {
	lp.MoveCursorTo(t.inner_left+1, t.inner_top+row+1)
	idx := t.first_line + row
	if !t.supported {
		idx = t.fallback_pos/t.cell_height + row
	}
	text, sgr := "", ""
	if idx >= 0 && idx < len(t.lines) {
		text, sgr = t.lines[idx].text, t.lines[idx].sgr
	}
	left := t.text_left - t.inner_left
	right := max(0, t.inner_width-left-wcswidth.Stringwidth(text))
	lp.QueueWriteString(strings.Repeat(" ", left) + sgr + text + "\x1b[m" + strings.Repeat(" ", right))
}

// draw_scroll_indicator draws the scroll bar in the right edge of the box
func (t *text_area) draw_scroll_indicator(lp *loop.Loop) {
	thumb_start, thumb_end := 0, 0
	if total := len(t.lines); total > t.inner_height && t.inner_height > 0 {
		size := max(1, t.inner_height*t.inner_height/total)
		frac := float64(t.position()) / float64(max(1, t.max_position()))
		thumb_start = int(frac*float64(t.inner_height-size) + 0.5)
		thumb_end = thumb_start + size
	}
	x := t.box_left + t.box_width
	for row := range t.inner_height {
		lp.MoveCursorTo(x, t.inner_top+row+1)
		if row >= thumb_start && row < thumb_end {
			lp.QueueWriteString("\x1b[36m┃\x1b[m")
		} else {
			lp.QueueWriteString("│")
		}
	}
}

// draw draws the box and all its text and defines the smooth scroll region
func (t *text_area) draw(lp *loop.Loop) {
	if !t.visible {
		return
	}
	lp.MoveCursorTo(t.box_left+1, t.box_top+1)
	lp.QueueWriteString("╭" + strings.Repeat("─", t.inner_width) + "╮")
	for row := range t.inner_height {
		lp.MoveCursorTo(t.box_left+1, t.inner_top+row+1)
		lp.QueueWriteString("│")
		t.paint_row(lp, row)
	}
	lp.MoveCursorTo(t.box_left+1, t.box_top+t.box_height)
	lp.QueueWriteString("╰" + strings.Repeat("─", t.inner_width) + "╯")
	t.draw_scroll_indicator(lp)
	if t.supported {
		lp.DefineSmoothScrollRegion(loop.SmoothScrollRegion{
			Id: text_region_id, X: uint32(t.inner_left + 1), Y: uint32(t.inner_top + 1),
			Width: uint32(t.inner_width), Height: uint32(t.inner_height), Capacity: text_region_capacity,
		})
	}
}

// scroll scrolls the text by the specified number of lines, which can be
// fractional. Must be called inside an atomic update, so that the rows moving
// into the region are drawn together with the scrolling.
func (t *text_area) scroll(lp *loop.Loop, lines float64) {
	if !t.visible {
		return
	}
	t.pending_pixels += lines * float64(t.cell_height)
	d := int(t.pending_pixels)
	t.pending_pixels -= float64(d)
	pos := t.position()
	d = max(0, min(pos+d, t.max_position())) - pos
	if d == 0 {
		t.pending_pixels = 0
		return
	}
	if !t.supported {
		before := t.fallback_pos / t.cell_height
		t.fallback_pos += d
		if t.fallback_pos/t.cell_height != before {
			for row := range t.inner_height {
				t.paint_row(lp, row)
			}
			t.draw_scroll_indicator(lp)
		}
		return
	}
	// The same calculation as performed by the terminal, to know which rows
	// move into the region, see the smooth scrolling protocol docs
	h := t.cell_height
	moved, shift := t.offset-d, 0
	if d > 0 {
		if moved < 0 {
			shift = (-moved + h - 1) / h
		}
	} else if moved > 0 {
		shift = -((moved + h - 1) / h)
	}
	t.offset = moved + shift*h
	t.first_line += shift
	lp.SmoothScroll(text_region_id, d)
	n := min(max(shift, -shift), t.inner_height)
	start := 0
	if shift > 0 {
		start = t.inner_height - n
	}
	for row := start; row < start+n; row++ {
		t.paint_row(lp, row)
	}
	t.draw_scroll_indicator(lp)
}
