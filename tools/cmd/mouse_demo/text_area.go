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
• Scroll this text with a mouse wheel or a touchpad. With a touchpad or a high resolution wheel it scrolls smoothly, pixel by pixel, following your fingers, using the smooth scrolling protocol. The bar on the right edge of this box shows the position in the text, drag it with the mouse to scroll, or click above or below it to scroll by a page.
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
	cell_width   int
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
	// The state of the thumb of the scroll indicator: whether it is being
	// dragged, the vertical distance in pixels from its top to the mouse when
	// the drag started, and whether the mouse is over it
	dragging       bool
	grab_offset    float64
	hovering_thumb bool
	// The image used to draw the thumb, when the terminal supports images
	thumb_image thumb_image
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
	t.cell_width = max(1, int(sz.CellWidth))
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

// When the terminal does not support images, the thumb of the scroll
// indicator is drawn with block characters in steps of one eighth of a cell,
// so that it moves smoothly as the text scrolls. Its geometry is then computed
// in these steps.
const eighths_per_cell = 8

// lower_blocks[n] is a block filling the lower n eighths of a cell
var lower_blocks = [eighths_per_cell + 1]string{" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"}

// thumb returns the position and size of the thumb of the scroll indicator
// in units of 1/units_per_cell of a cell, with zero being the top of the
// interior of the box. size is zero when all the text fits in the box.
func (t *text_area) thumb(units_per_cell int) (start, size int) {
	total := len(t.lines)
	if total <= t.inner_height || t.inner_height < 1 {
		return 0, 0
	}
	track := t.inner_height * units_per_cell
	// The thumb is at least one cell high, so that it is easy to grab and,
	// when drawn with block characters, no cell contains only the middle of
	// the thumb, which cannot be drawn with them
	size = max(units_per_cell, track*t.inner_height/total)
	frac := float64(t.position()) / float64(max(1, t.max_position()))
	start = int(frac*float64(track-size) + 0.5)
	return
}

// The horizontal extent, in zero based cells, in which the scroll indicator
// responds to the mouse: the indicator in the right edge of the box and the
// cell to its left, as a single cell is a small target
func (t *text_area) indicator_hit_cols() (first, last int) {
	last = t.box_left + t.box_width - 1
	return last - 1, last
}

// thumb_pixels returns the top of the thumb, relative to the top of the
// interior of the box, its height and the height of the track, in pixels
func (t *text_area) thumb_pixels() (top, height, track float64) {
	units := t.thumb_units_per_cell()
	start, size := t.thumb(units)
	px_per_unit := float64(t.cell_height) / float64(units)
	return float64(start) * px_per_unit, float64(size) * px_per_unit, float64(t.inner_height * t.cell_height)
}

// The thumb is positioned in pixels when drawn as an image and in eighths
// of a cell when drawn with block characters
func (t *text_area) thumb_units_per_cell() int {
	if t.thumb_image.supported {
		return t.cell_height
	}
	return eighths_per_cell
}

// hit_test returns whether the mouse is over the scroll indicator and if so,
// whether it is over the thumb, or above or below it
func (t *text_area) hit_test(ev *loop.MouseEvent) (on_indicator bool, where int) {
	first, last := t.indicator_hit_cols()
	if !t.visible || ev.Cell.X < first || ev.Cell.X > last || ev.Cell.Y < t.inner_top || ev.Cell.Y >= t.inner_top+t.inner_height {
		return false, 0
	}
	top, height, _ := t.thumb_pixels()
	if height == 0 {
		return false, 0
	}
	y := float64(ev.Pixel.Y - t.inner_top*t.cell_height)
	switch {
	case y < top:
		return true, -1
	case y >= top+height:
		return true, 1
	}
	return true, 0
}

// draw_scroll_indicator draws the scroll bar in the right edge of the box
func (t *text_area) draw_scroll_indicator(lp *loop.Loop) {
	if t.thumb_image.supported {
		t.draw_scroll_indicator_image(lp)
		return
	}
	start, size := t.thumb(eighths_per_cell)
	end := start + size
	color := "36"
	if t.dragging || t.hovering_thumb {
		color = "96"
	}
	x := t.box_left + t.box_width
	for row := range t.inner_height {
		lp.MoveCursorTo(x, t.inner_top+row+1)
		cell_top, cell_bottom := row*eighths_per_cell, (row+1)*eighths_per_cell
		a, b := max(start, cell_top), min(end, cell_bottom)
		switch {
		case b <= a:
			lp.QueueWriteString("│")
		case b == cell_bottom:
			// The thumb covers the lower part, or all, of this cell
			lp.QueueWriteString("\x1b[" + color + "m" + lower_blocks[b-a] + "\x1b[m")
		default:
			// The thumb covers the upper part of this cell, draw the lower
			// part, not covered by it, in the background color using reverse video
			lp.QueueWriteString("\x1b[" + color + ";7m" + lower_blocks[cell_bottom-b] + "\x1b[m")
		}
	}
}

// draw_scroll_indicator_image draws the scroll bar as a line in the right
// edge of the box, with the thumb an image over it
func (t *text_area) draw_scroll_indicator_image(lp *loop.Loop) {
	start, size := t.thumb(t.cell_height)
	if size == 0 {
		t.thumb_image.hide(lp)
		return
	}
	x := t.box_left + t.box_width - 1
	key := thumb_image_key{width: t.cell_width, height: size, hovered: t.dragging || t.hovering_thumb}
	t.thumb_image.draw(lp, key, x, t.inner_top, start, t.cell_height)
}

// set_images_supported is called when the terminal is found to support images
func (t *text_area) set_images_supported(lp *loop.Loop) {
	if t.thumb_image.supported {
		return
	}
	t.thumb_image.supported = true
	if t.visible {
		// Replace the thumb drawn with block characters by the line
		t.draw_right_edge(lp)
		t.draw_scroll_indicator(lp)
	}
}

// draw_right_edge draws the line in the right edge of the box, over which the
// thumb image is drawn
func (t *text_area) draw_right_edge(lp *loop.Loop) {
	x := t.box_left + t.box_width
	for row := range t.inner_height {
		lp.MoveCursorTo(x, t.inner_top+row+1)
		lp.QueueWriteString("│")
	}
}

// handle_mouse handles mouse events for dragging the thumb of the scroll
// indicator and clicking in its track, returning true if the event was
// consumed. Must be called inside an atomic update.
func (t *text_area) handle_mouse(lp *loop.Loop, ev *loop.MouseEvent) bool {
	if !t.visible {
		t.dragging, t.hovering_thumb = false, false
		return false
	}
	left_held := ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0
	on_indicator, where := t.hit_test(ev)
	consumed := false
	was_hovering, was_dragging := t.hovering_thumb, t.dragging
	switch ev.Event_type {
	case loop.MOUSE_PRESS:
		if left_held && on_indicator {
			consumed = true
			if where == 0 {
				top, _, _ := t.thumb_pixels()
				t.dragging = true
				t.grab_offset = float64(ev.Pixel.Y-t.inner_top*t.cell_height) - top
			} else {
				// Page up or down
				t.scroll_pixels(lp, where*max(1, t.inner_height-1)*t.cell_height)
			}
		}
	case loop.MOUSE_MOVE:
		if t.dragging {
			if left_held {
				consumed = true
				t.drag_to(lp, ev.Pixel.Y)
			} else {
				// The release was not reported, for instance, because it
				// happened outside the window
				t.dragging = false
			}
		}
	case loop.MOUSE_RELEASE:
		if t.dragging && ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0 {
			consumed = true
			t.dragging = false
		}
	}
	t.hovering_thumb = ev.Event_type != loop.MOUSE_LEAVE && on_indicator && where == 0
	if was_hovering != t.hovering_thumb || was_dragging != t.dragging {
		t.draw_scroll_indicator(lp)
	}
	return consumed
}

// drag_to scrolls the text so that the thumb, dragged by the mouse, is at
// the specified vertical pixel position of the mouse
func (t *text_area) drag_to(lp *loop.Loop, y int) {
	_, height, track := t.thumb_pixels()
	if track <= height {
		return
	}
	top := max(0, min(float64(y-t.inner_top*t.cell_height)-t.grab_offset, track-height))
	target := int(top/(track-height)*float64(t.max_position()) + 0.5)
	t.scroll_pixels(lp, target-t.position())
}

// draw draws the box and all its text and defines the smooth scroll region.
// Must be called after clearing the screen.
func (t *text_area) draw(lp *loop.Loop) {
	// Clearing the screen removes the thumb image
	t.thumb_image.forget()
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
	if t.thumb_image.supported {
		t.draw_right_edge(lp)
	}
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
	if d != 0 && !t.scroll_pixels(lp, d) {
		// At the start or end of the text
		t.pending_pixels = 0
	}
}

// scroll_pixels scrolls the text by the specified number of pixels, limited
// to the text, returning false if it could not be scrolled at all. Must be
// called inside an atomic update, so that the rows moving into the region are
// drawn together with the scrolling.
func (t *text_area) scroll_pixels(lp *loop.Loop, d int) bool {
	if !t.visible {
		return false
	}
	pos := t.position()
	d = max(0, min(pos+d, t.max_position())) - pos
	if d == 0 {
		return false
	}
	if !t.supported {
		before := t.fallback_pos / t.cell_height
		t.fallback_pos += d
		if t.fallback_pos/t.cell_height != before {
			for row := range t.inner_height {
				t.paint_row(lp, row)
			}
		}
		t.draw_scroll_indicator(lp)
		return true
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
	return true
}
