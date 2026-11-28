// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package scrolling

import (
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

// Indicator is a vertical scroll bar, one cell wide, showing the position in
// the content with a thumb that can be dragged with the mouse. Clicking above
// or below the thumb scrolls by a page. The thumb is drawn as an image, with
// pixel precision, when the terminal supports it, see graphics.ScrollThumb,
// otherwise with block characters, in steps of one eighth of a cell.
type Indicator struct {
	// The thumb image, if nil, the thumb is always drawn with block characters
	Thumb *graphics.ScrollThumb
	// The SGR colors of the thumb when drawn with block characters, they
	// should match the palette colors of the thumb image. Default to cyan
	// and bright cyan.
	Color, HoveredColor string
	// SGR codes for the line drawn in the track when the thumb is an image,
	// or when there is nothing to scroll and AlwaysDrawTrack is set
	TrackStyle string
	// Draw the line of the track even when everything fits, for instance,
	// when it is part of a border
	AlwaysDrawTrack bool

	// Whether the thumb is being dragged and whether the mouse is over it,
	// programs can use these to set the mouse pointer shape
	Dragging, Hovering bool

	// The zero based cell position of the top of the track and its height in cells
	x, y, height            int
	cell_width, cell_height int
	// The scroll position and its maximum
	pos, max_pos int
	// The height of the visible part of the content and of all of it, in any unit
	viewport, total int
	// The vertical distance in pixels from the top of the thumb to the mouse
	// when the drag started
	grab_offset float64
}

// SetGeometry sets the zero based cell position of the top of the track,
// its height in cells and the size of a cell in pixels
func (s *Indicator) SetGeometry(x, y, height, cell_width, cell_height int) {
	s.x, s.y, s.height, s.cell_width, s.cell_height = x, y, height, max(1, cell_width), max(1, cell_height)
}

// SetPosition sets the scroll position and its maximum, in any unit, and
// the height of the visible part of the content and of all of it, in any
// unit, that determine the size of the thumb
func (s *Indicator) SetPosition(pos, max_pos, viewport, total int) {
	s.pos, s.max_pos, s.viewport, s.total = pos, max_pos, viewport, total
}

// SetFromScroller sets the position from the specified Scroller
func (s *Indicator) SetFromScroller(sc *Scroller) {
	s.SetPosition(sc.Position(), sc.MaxPosition(), sc.Height(), sc.NumLines())
}

// Visible returns whether there is a thumb, that is, whether there is
// content that does not fit
func (s *Indicator) Visible() bool {
	return s.height > 0 && s.viewport > 0 && s.total > s.viewport
}

func (s *Indicator) uses_image() bool { return s.Thumb != nil && s.Thumb.Supported }

func (s *Indicator) units_per_cell() int {
	if s.uses_image() {
		return s.cell_height
	}
	return graphics.EighthsPerCell
}

// ThumbGeometry returns the position and size of the thumb in units of
// 1/units_per_cell of a cell, with zero being the top of the track. size is
// zero when everything fits.
func (s *Indicator) ThumbGeometry(units_per_cell int) (start, size int) {
	if !s.Visible() {
		return 0, 0
	}
	track := s.height * units_per_cell
	// The thumb is at least one cell high, so that it is easy to grab and,
	// when drawn with block characters, no cell contains only the middle of
	// the thumb, which cannot be drawn with them
	size = min(track, max(units_per_cell, int(int64(track)*int64(s.viewport)/int64(s.total))))
	frac := 0.
	if s.max_pos > 0 {
		frac = max(0, min(1, float64(s.pos)/float64(s.max_pos)))
	}
	start = int(frac*float64(track-size) + 0.5)
	return
}

// thumb_pixels returns the top of the thumb, relative to the top of the
// track, its height and the height of the track, in pixels
func (s *Indicator) thumb_pixels() (top, height, track float64) {
	units := s.units_per_cell()
	start, size := s.ThumbGeometry(units)
	px_per_unit := float64(s.cell_height) / float64(units)
	return float64(start) * px_per_unit, float64(size) * px_per_unit, float64(s.height * s.cell_height)
}

func (s *Indicator) colors() (normal, hovered string) {
	normal, hovered = s.Color, s.HoveredColor
	if normal == "" {
		normal = "36"
	}
	if hovered == "" {
		hovered = "96"
	}
	return
}

// Draw draws the indicator. Does not change the SGR attributes in effect.
func (s *Indicator) Draw(lp *loop.Loop) {
	if s.height < 1 {
		return
	}
	track := "\x1b[m" + s.TrackStyle + "│\x1b[m"
	if !s.Visible() {
		s.Dragging, s.Hovering = false, false
		if s.Thumb != nil {
			s.Thumb.Hide(lp)
		}
		cell := utils.IfElse(s.AlwaysDrawTrack, track, " ")
		for row := range s.height {
			lp.MoveCursorTo(s.x+1, s.y+row+1)
			lp.QueueWriteString(cell)
		}
		return
	}
	hovered := s.Dragging || s.Hovering
	if s.uses_image() {
		for row := range s.height {
			lp.MoveCursorTo(s.x+1, s.y+row+1)
			lp.QueueWriteString(track)
		}
		start, size := s.ThumbGeometry(s.cell_height)
		key := graphics.ScrollThumbKey{Width: s.cell_width, Height: size, Hovered: hovered}
		s.Thumb.Draw(lp, key, s.x, s.y, start, s.cell_height)
		return
	}
	normal, hc := s.colors()
	color := utils.IfElse(hovered, hc, normal)
	start, size := s.ThumbGeometry(graphics.EighthsPerCell)
	for row := range s.height {
		lp.MoveCursorTo(s.x+1, s.y+row+1)
		lp.QueueWriteString(graphics.ThumbBlockCell(row, start, start+size, color))
	}
}

// Free deletes the thumb image from the terminal
func (s *Indicator) Free(lp *loop.Loop) {
	if s.Thumb != nil {
		s.Thumb.Free(lp)
	}
}

// HitTest returns whether the mouse is over the indicator and if so, whether
// it is over the thumb (0), or above (-1) or below (1) it. The column to the
// left of the indicator counts as well, as a single column is a small target.
func (s *Indicator) HitTest(ev *loop.MouseEvent) (on_indicator bool, where int) {
	if !s.Visible() || ev.Cell.X < s.x-1 || ev.Cell.X > s.x || ev.Cell.Y < s.y || ev.Cell.Y >= s.y+s.height {
		return false, 0
	}
	top, height, _ := s.thumb_pixels()
	y := float64(ev.Pixel.Y - s.y*s.cell_height)
	switch {
	case y < top:
		return true, -1
	case y >= top+height:
		return true, 1
	}
	return true, 0
}

// IndicatorActions are called by Indicator.HandleMouse() to scroll
type IndicatorActions struct {
	// Called when the thumb is dragged, with the position to scroll to, in
	// the units used for SetPosition()
	ScrollTo func(pos int)
	// Called when the track is clicked above (-1) or below (1) the thumb
	Page func(direction int)
}

// HandleMouse handles mouse events for dragging the thumb and clicking in
// the track, returning whether the event was consumed and whether Dragging or
// Hovering changed, in which case the indicator should be drawn again.
func (s *Indicator) HandleMouse(ev *loop.MouseEvent, actions IndicatorActions) (consumed, changed bool) {
	left_held := ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0
	on_indicator, where := s.HitTest(ev)
	was_hovering, was_dragging := s.Hovering, s.Dragging
	switch ev.Event_type {
	case loop.MOUSE_PRESS:
		if left_held && on_indicator {
			consumed = true
			if where == 0 {
				top, _, _ := s.thumb_pixels()
				s.Dragging = true
				s.grab_offset = float64(ev.Pixel.Y-s.y*s.cell_height) - top
			} else if actions.Page != nil {
				actions.Page(where)
			}
		}
	case loop.MOUSE_MOVE:
		if s.Dragging {
			if left_held {
				consumed = true
				if actions.ScrollTo != nil {
					actions.ScrollTo(s.position_for_drag(ev.Pixel.Y))
				}
			} else {
				// The release was not reported, for instance, because it
				// happened outside the window
				s.Dragging = false
			}
		}
	case loop.MOUSE_RELEASE:
		if s.Dragging && left_held {
			consumed = true
			s.Dragging = false
		}
	}
	if !s.Visible() {
		s.Dragging = false
	}
	s.Hovering = ev.Event_type != loop.MOUSE_LEAVE && on_indicator && where == 0
	return consumed, was_hovering != s.Hovering || was_dragging != s.Dragging
}

// position_for_drag returns the scroll position for the thumb, being
// dragged, to be at the specified vertical pixel position of the mouse
func (s *Indicator) position_for_drag(y int) int {
	_, height, track := s.thumb_pixels()
	if track <= height {
		return 0
	}
	top := max(0, min(float64(y-s.y*s.cell_height)-s.grab_offset, track-height))
	return int(top/(track-height)*float64(s.max_pos) + 0.5)
}
