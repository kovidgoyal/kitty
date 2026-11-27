// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package graphics

import (
	"math"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

// ScrollThumb draws the thumb of a scroll indicator as an image, positioned
// with pixel precision. The image uses indexed color data, so that it is drawn
// in the colors of the terminal color scheme, and redrawn when they change.
// Whether the terminal supports the graphics protocol with indexed color data
// is detected with a query, programs should draw the thumb with block
// characters when it does not.
type ScrollThumb struct {
	ImageId     uint32
	PlacementId uint32
	// The colors of the thumb, as indices into the terminal color palette
	Color, HoveredColor uint8
	// The width of the thumb as a fraction of the width of the image
	WidthFraction float64

	// Whether the terminal supports the graphics protocol with indexed color data
	Supported bool
	// The appearance of the image last transmitted, if any
	transmitted     ScrollThumbKey
	has_transmitted bool
	// Whether the image is currently placed on the screen
	placed bool
}

// The appearance of the thumb image, it is transmitted again when it changes
type ScrollThumbKey struct {
	Width, Height int
	Hovered       bool
}

// NewScrollThumb returns a thumb drawn in cyan, or bright cyan when hovered
func NewScrollThumb(image_id uint32) *ScrollThumb {
	return &ScrollThumb{ImageId: image_id, PlacementId: 1, Color: 6, HoveredColor: 14, WidthFraction: 0.45}
}

// Query asks the terminal whether it supports the graphics protocol with
// indexed color data, pass responses to IsSupportResponse
func (t *ScrollThumb) Query(lp *loop.Loop) {
	g := GraphicsCommand{}
	g.SetAction(GRT_action_query).SetImageId(t.ImageId).SetFormat(GRT_format_indexed)
	g.SetDataWidth(1).SetDataHeight(1).SetTransmission(GRT_transmission_direct)
	_ = g.WriteWithPayloadToLoop(lp, []byte{0})
}

// IsSupportResponse returns true if raw, the contents of an APC escape code,
// is a successful response to Query
func (t *ScrollThumb) IsSupportResponse(raw []byte) bool {
	g := GraphicsCommandFromAPC(raw)
	return g != nil && g.ImageId() == t.ImageId && g.ResponseMessage() == "OK"
}

// Render returns the pixels, as palette index and alpha pairs, of a thumb of
// the specified size: a vertical bar with rounded ends, centered
// horizontally, anti-aliased
func (t *ScrollThumb) Render(key ScrollThumbKey) []byte {
	w, h := key.Width, key.Height
	c := t.Color
	if key.Hovered {
		c = t.HoveredColor
	}
	ans := make([]byte, 2*w*h)
	radius := max(1, math.Round(float64(w)*t.WidthFraction)) / 2
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

// Draw places the thumb image with its top left corner at the specified
// position in pixels, relative to the top left corner of the cell at the
// zero based cell position (x, y), transmitting it first if its appearance
// has changed. Does not move the cursor.
func (t *ScrollThumb) Draw(lp *loop.Loop, key ScrollThumbKey, x, y, top int, cell_height int) {
	if !t.has_transmitted || t.transmitted != key {
		g := GraphicsCommand{}
		g.SetAction(GRT_action_transmit).SetQuiet(GRT_quiet_silent).SetImageId(t.ImageId)
		g.SetFormat(GRT_format_indexed_alpha).SetDataWidth(uint64(key.Width)).SetDataHeight(uint64(key.Height))
		_ = g.WriteWithPayloadToLoop(lp, t.Render(key))
		t.transmitted, t.has_transmitted = key, true
	}
	// Placing the image with the same placement id moves it
	lp.MoveCursorTo(x+1, y+top/cell_height+1)
	g := GraphicsCommand{}
	g.SetAction(GRT_action_display).SetQuiet(GRT_quiet_silent).SetImageId(t.ImageId)
	g.SetPlacementId(t.PlacementId).SetYOffset(uint64(top % cell_height)).SetCursorMovement(GRT_cursor_static)
	_ = g.WriteWithPayloadToLoop(lp, nil)
	t.placed = true
}

// Hide removes the thumb image from the screen, keeping its data
func (t *ScrollThumb) Hide(lp *loop.Loop) {
	if !t.placed {
		return
	}
	g := GraphicsCommand{}
	g.SetAction(GRT_action_delete).SetQuiet(GRT_quiet_silent).SetDelete(GRT_delete_by_id).SetImageId(t.ImageId)
	_ = g.WriteWithPayloadToLoop(lp, nil)
	t.placed = false
}

// Free deletes the thumb image and its data from the terminal
func (t *ScrollThumb) Free(lp *loop.Loop) {
	if !t.has_transmitted {
		return
	}
	g := GraphicsCommand{}
	g.SetAction(GRT_action_delete).SetQuiet(GRT_quiet_silent).SetDelete(GRT_free_by_id).SetImageId(t.ImageId)
	_ = g.WriteWithPayloadToLoop(lp, nil)
	t.has_transmitted, t.placed = false, false
}

// Forget must be called when the screen is cleared in a way that removes
// the image from it and may delete its data
func (t *ScrollThumb) Forget() {
	t.has_transmitted, t.placed = false, false
}

// The thumb of a scroll indicator drawn with block characters, when the terminal does not
// support images, is positioned in steps of one eighth of a cell, so that it
// moves smoothly.
const EighthsPerCell = 8

// LowerBlocks[n] is a block filling the lower n eighths of a cell
var LowerBlocks = [EighthsPerCell + 1]string{" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"}

// ThumbBlockCell returns the text to draw a cell of a scroll indicator drawn
// with block characters, for a thumb from start to end in eighths of a cell,
// relative to the top of the track. color is an SGR foreground color code.
// The text resets all SGR attributes before and after, so it does not depend
// on the formatting in effect when it is drawn.
func ThumbBlockCell(row, start, end int, color string) string {
	cell_top, cell_bottom := row*EighthsPerCell, (row+1)*EighthsPerCell
	a, b := max(start, cell_top), min(end, cell_bottom)
	switch {
	case b <= a:
		return "\x1b[m│"
	case b == cell_bottom:
		// The thumb covers the lower part, or all, of this cell
		return "\x1b[0;" + color + "m" + LowerBlocks[b-a] + "\x1b[m"
	default:
		// The thumb covers the upper part of this cell, draw the lower
		// part, not covered by it, in the background color using reverse video
		return "\x1b[0;" + color + ";7m" + LowerBlocks[cell_bottom-b] + "\x1b[m"
	}
}
