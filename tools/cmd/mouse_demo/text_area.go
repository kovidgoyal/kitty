// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package mouse_demo

import (
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/scrolling"
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
	lp                                               *loop.Loop
	// Scrolls the lines of text in the interior of the box
	scroller scrolling.Scroller
	// The scroll bar in the right edge of the box
	indicator scrolling.Indicator
}

func new_text_area(lp *loop.Loop, thumb_image_id uint32) *text_area {
	t := &text_area{lp: lp}
	t.scroller = scrolling.Scroller{Id: text_region_id, Capacity: text_region_capacity, Paint: t.paint_row}
	t.indicator = scrolling.Indicator{Thumb: graphics.NewScrollThumb(thumb_image_id), AlwaysDrawTrack: true}
	return t
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
	t.wrap(text_width)
	t.scroller.SetNumLines(len(t.lines))
	t.scroller.SetGeometry(t.inner_left, t.inner_top, t.inner_width, t.inner_height, t.cell_height)
	t.indicator.SetGeometry(t.box_left+t.box_width-1, t.inner_top, t.inner_height, t.cell_width, t.cell_height)
}

func (t *text_area) paint_row(row, idx int) {
	lp := t.lp
	lp.MoveCursorTo(t.inner_left+1, t.inner_top+row+1)
	text, sgr := "", ""
	if idx >= 0 && idx < len(t.lines) {
		text, sgr = t.lines[idx].text, t.lines[idx].sgr
	}
	left := t.text_left - t.inner_left
	right := max(0, t.inner_width-left-wcswidth.Stringwidth(text))
	lp.QueueWriteString(strings.Repeat(" ", left) + sgr + text + "\x1b[m" + strings.Repeat(" ", right))
}

func (t *text_area) draw_scroll_indicator(lp *loop.Loop) {
	t.indicator.SetFromScroller(&t.scroller)
	t.indicator.Draw(lp)
}

// set_images_supported is called when the terminal is found to support images
func (t *text_area) set_images_supported(lp *loop.Loop) {
	if t.indicator.Thumb.Supported {
		return
	}
	t.indicator.Thumb.Supported = true
	if t.visible {
		t.draw_scroll_indicator(lp)
	}
}

// handle_mouse handles mouse events for dragging the thumb of the scroll
// indicator and clicking in its track, returning true if the event was
// consumed. Must be called inside an atomic update.
func (t *text_area) handle_mouse(lp *loop.Loop, ev *loop.MouseEvent) bool {
	if !t.visible {
		t.indicator.Dragging, t.indicator.Hovering = false, false
		return false
	}
	consumed, changed := t.indicator.HandleMouse(ev, scrolling.IndicatorActions{
		ScrollTo: func(pos int) { t.scroll_to(lp, pos) },
		Page: func(direction int) {
			t.scroll_to(lp, t.scroller.Position()+direction*max(1, t.inner_height-1)*t.cell_height)
		},
	})
	if changed {
		t.draw_scroll_indicator(lp)
	}
	return consumed
}

func (t *text_area) scroll_to(lp *loop.Loop, pos int) {
	if t.scroller.ScrollTo(lp, pos) {
		t.draw_scroll_indicator(lp)
	}
}

// draw draws the box and all its text and defines the smooth scroll region.
// Must be called after clearing the screen.
func (t *text_area) draw(lp *loop.Loop) {
	// Clearing the screen removes the thumb image
	t.indicator.Thumb.Forget()
	// and the smooth scroll region, when it is resized
	t.scroller.Invalidate()
	if !t.visible {
		return
	}
	lp.MoveCursorTo(t.box_left+1, t.box_top+1)
	lp.QueueWriteString("╭" + strings.Repeat("─", t.inner_width) + "╮")
	for row := range t.inner_height {
		lp.MoveCursorTo(t.box_left+1, t.inner_top+row+1)
		lp.QueueWriteString("│")
	}
	lp.MoveCursorTo(t.box_left+1, t.box_top+t.box_height)
	lp.QueueWriteString("╰" + strings.Repeat("─", t.inner_width) + "╯")
	t.scroller.Draw(lp)
	t.draw_scroll_indicator(lp)
}

// handle_wheel scrolls the text in response to wheel events, returning true
// if the event is a wheel event. Must be called inside an atomic update.
func (t *text_area) handle_wheel(lp *loop.Loop, ev *loop.MouseEvent) bool {
	if !t.visible {
		return false
	}
	is_wheel, scrolled := t.scroller.HandleWheel(lp, ev, lines_per_click)
	if scrolled {
		t.draw_scroll_indicator(lp)
	}
	return is_wheel
}
