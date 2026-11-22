// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package mouse_demo

import (
	"math"

	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

// The thumb of the scroll indicator is drawn as an image, using the kitty
// graphics protocol, positioned with pixel precision over the line in the
// right edge of the box. The image uses indexed color data, so that it is
// drawn in the colors of the terminal color scheme, and redrawn when they
// change. Terminals that do not support the graphics protocol, or indexed color
// data, are detected with a query, the thumb is then drawn with block characters.

const (
	thumb_image_id     = 7301
	thumb_placement_id = 1
	// The width of the thumb as a fraction of the cell width
	thumb_width_fraction = 0.45
)

// The colors of the thumb, as indices into the terminal color palette, the
// same colors as are used to draw it with block characters: cyan and bright cyan
const (
	thumb_color         uint8 = 6
	thumb_hovered_color uint8 = 14
)

// The appearance of the thumb image, it is transmitted again when it changes
type thumb_image_key struct {
	width, height int
	hovered       bool
}

type thumb_image struct {
	// Whether the terminal supports the graphics protocol with indexed color data
	supported bool
	// The appearance of the image last transmitted, if any
	transmitted     thumb_image_key
	has_transmitted bool
	// Whether the image is currently placed on the screen
	placed bool
}

// query_graphics_support asks the terminal whether it supports the graphics
// protocol with indexed color data, the response is handled by handle_graphics_response
func query_graphics_support(lp *loop.Loop) {
	g := graphics.GraphicsCommand{}
	g.SetAction(graphics.GRT_action_query).SetImageId(thumb_image_id).SetFormat(graphics.GRT_format_indexed)
	g.SetDataWidth(1).SetDataHeight(1).SetTransmission(graphics.GRT_transmission_direct)
	_ = g.WriteWithPayloadToLoop(lp, []byte{0})
}

// is_graphics_support_response returns true if raw, the contents of an APC
// escape code, is a successful response to query_graphics_support
func is_graphics_support_response(raw []byte) bool {
	g := graphics.GraphicsCommandFromAPC(raw)
	return g != nil && g.ImageId() == thumb_image_id && g.ResponseMessage() == "OK"
}

// render_thumb returns the pixels, as palette index and alpha pairs, of a thumb of the specified size: a
// vertical bar with rounded ends, centered horizontally, anti-aliased
func render_thumb(key thumb_image_key) []byte {
	w, h := key.width, key.height
	c := thumb_color
	if key.hovered {
		c = thumb_hovered_color
	}
	ans := make([]byte, 2*w*h)
	radius := max(1, math.Round(float64(w)*thumb_width_fraction)) / 2
	cx := float64(w) / 2
	// The ends of the segment that is the axis of the bar
	top, bottom := radius, float64(h)-radius
	if bottom < top {
		top, bottom = float64(h)/2, float64(h)/2
	}
	for y := range h {
		py := float64(y) + 0.5
		dy := 0.
		if py < top {
			dy = top - py
		} else if py > bottom {
			dy = py - bottom
		}
		for x := range w {
			dx := float64(x) + 0.5 - cx
			coverage := max(0, min(1, radius-math.Hypot(dx, dy)+0.5))
			if coverage > 0 {
				i := 2 * (y*w + x)
				ans[i], ans[i+1] = c, uint8(math.Round(coverage*255))
			}
		}
	}
	return ans
}

// draw places the thumb image with its top left corner at the specified
// position in pixels, relative to the top left corner of the cell at the
// zero based cell position (x, y), transmitting it first if its appearance
// has changed. Does not move the cursor.
func (ti *thumb_image) draw(lp *loop.Loop, key thumb_image_key, x, y, top int, cell_height int) {
	if !ti.has_transmitted || ti.transmitted != key {
		g := graphics.GraphicsCommand{}
		g.SetAction(graphics.GRT_action_transmit).SetQuiet(graphics.GRT_quiet_silent).SetImageId(thumb_image_id)
		g.SetFormat(graphics.GRT_format_indexed_alpha).SetDataWidth(uint64(key.width)).SetDataHeight(uint64(key.height))
		_ = g.WriteWithPayloadToLoop(lp, render_thumb(key))
		ti.transmitted, ti.has_transmitted = key, true
	}
	// Placing the image with the same placement id moves it
	lp.MoveCursorTo(x+1, y+top/cell_height+1)
	g := graphics.GraphicsCommand{}
	g.SetAction(graphics.GRT_action_display).SetQuiet(graphics.GRT_quiet_silent).SetImageId(thumb_image_id)
	g.SetPlacementId(thumb_placement_id).SetYOffset(uint64(top % cell_height)).SetCursorMovement(graphics.GRT_cursor_static)
	_ = g.WriteWithPayloadToLoop(lp, nil)
	ti.placed = true
}

// hide removes the thumb image from the screen, keeping its data
func (ti *thumb_image) hide(lp *loop.Loop) {
	if !ti.placed {
		return
	}
	g := graphics.GraphicsCommand{}
	g.SetAction(graphics.GRT_action_delete).SetQuiet(graphics.GRT_quiet_silent).SetDelete(graphics.GRT_delete_by_id).SetImageId(thumb_image_id)
	_ = g.WriteWithPayloadToLoop(lp, nil)
	ti.placed = false
}

// free deletes the thumb image and its data from the terminal
func (ti *thumb_image) free(lp *loop.Loop) {
	if !ti.has_transmitted {
		return
	}
	g := graphics.GraphicsCommand{}
	g.SetAction(graphics.GRT_action_delete).SetQuiet(graphics.GRT_quiet_silent).SetDelete(graphics.GRT_free_by_id).SetImageId(thumb_image_id)
	_ = g.WriteWithPayloadToLoop(lp, nil)
	ti.has_transmitted, ti.placed = false, false
}

// forget is called when the screen is cleared, which removes the image
// from it and may delete its data
func (ti *thumb_image) forget() {
	ti.has_transmitted, ti.placed = false, false
}
