// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type LinePos interface {
	LessThan(other LinePos) bool
	Equal(other LinePos) bool
	MinX() int
	MaxX() int
}

type SelectionBoundary struct {
	line                  LinePos
	x                     int
	in_first_half_of_cell bool
}

func (self *SelectionBoundary) LessThan(other *SelectionBoundary) bool {
	if self.line.LessThan(other.line) {
		return true
	}
	if !self.line.Equal(other.line) {
		return false
	}
	if self.x == other.x {
		return !self.in_first_half_of_cell && other.in_first_half_of_cell
	}
	return self.x < other.x
}

func (self *SelectionBoundary) Equal(other SelectionBoundary) bool {
	if self.x != other.x || self.in_first_half_of_cell != other.in_first_half_of_cell {
		return false
	}
	if self.line == nil {
		return other.line == nil
	}
	return self.line.Equal(other.line)
}

type MouseSelection struct {
	start, end              SelectionBoundary
	is_active               bool
	min_y, max_y            int
	cell_width, cell_height int
	drag_scroll             struct {
		timer_id    loop.IdType
		pixel_gap   int
		mouse_event loop.MouseEvent
	}
}

func (self *MouseSelection) IsEmpty() bool  { return self.start.Equal(self.end) }
func (self *MouseSelection) IsActive() bool { return self.is_active }
func (self *MouseSelection) Finish()        { self.is_active = false }
func (self *MouseSelection) Clear()         { *self = MouseSelection{} }

func (ms *MouseSelection) StartNewSelection(ev *loop.MouseEvent, line LinePos, min_y, max_y, cell_width, cell_height int) {
	*ms = MouseSelection{cell_width: cell_width, cell_height: cell_height, min_y: min_y, max_y: max_y}
	ms.start.line = line
	ms.start.x = max(line.MinX(), min(ev.Cell.X, line.MaxX()))
	cell_start := cell_width * ev.Cell.X
	ms.start.in_first_half_of_cell = ev.Pixel.X <= cell_start+cell_width/2
	ms.end = ms.start
	ms.is_active = true
}

func (ms *MouseSelection) Update(ev *loop.MouseEvent, line LinePos) {
	ms.drag_scroll.timer_id = 0
	if ms.is_active {
		ms.end.x = max(line.MinX(), min(ev.Cell.X, line.MaxX()))
		cell_start := ms.cell_width * ms.end.x
		ms.end.in_first_half_of_cell = ev.Pixel.X <= cell_start+ms.cell_width/2
		ms.end.line = line
	}
}

func (ms *MouseSelection) LineBounds(line_pos LinePos) (start_x, end_x int) {
	if ms.IsEmpty() {
		return -1, -1
	}
	a, b := &ms.start, &ms.end
	if b.LessThan(a) {
		a, b = b, a
	}

	adjust_end := func(x int, b *SelectionBoundary) (int, int) {
		if b.in_first_half_of_cell {
			if b.x > x {
				return x, b.x - 1
			}
			return -1, -1
		}
		return x, b.x
	}

	adjust_start := func(a *SelectionBoundary, x int) (int, int) {
		if a.in_first_half_of_cell {
			return a.x, x
		}
		if x > a.x {
			return a.x + 1, x
		}
		return -1, -1
	}

	adjust_both := func(a, b *SelectionBoundary) (int, int) {
		if a.in_first_half_of_cell {
			return adjust_end(a.x, b)
		} else {
			if b.in_first_half_of_cell {
				s, e := a.x+1, b.x-1
				if e <= s {
					return -1, -1
				}
				return s, e
			} else {
				return adjust_start(a, b.x)
			}
		}
	}

	if a.line.LessThan(line_pos) {
		if line_pos.LessThan(b.line) {
			return line_pos.MinX(), line_pos.MaxX()
		} else if b.line.Equal(line_pos) {
			return adjust_end(line_pos.MinX(), b)
		}
	} else if a.line.Equal(line_pos) {
		if line_pos.LessThan(b.line) {
			return adjust_start(a, line_pos.MaxX())
		} else if b.line.Equal(line_pos) {
			return adjust_both(a, b)
		}
	}
	return -1, -1
}

func FormatPartOfLine(sgr string, start_x, end_x, y int) string { // uses zero based indices
	// DECCARA used to set formatting in specified region using zero based indexing
	return fmt.Sprintf("\x1b[%d;%d;%d;%d;%s$r", y+1, start_x+1, y+1, end_x+1, sgr)
}

func (ms *MouseSelection) LineFormatSuffix(line_pos LinePos, sgr string, y int) string {
	s, e := ms.LineBounds(line_pos)
	if s > -1 {
		return FormatPartOfLine(sgr, s, e, y)
	}
	return ""
}

func (ms *MouseSelection) StartLine() LinePos {
	return ms.start.line
}

func (ms *MouseSelection) EndLine() LinePos {
	return ms.end.line
}

func (ms *MouseSelection) OutOfVerticalBounds(ev *loop.MouseEvent) bool {
	return ev.Pixel.Y < ms.min_y*ms.cell_height || ev.Pixel.Y > (ms.max_y+1)*ms.cell_height
}

func (ms *MouseSelection) DragScrollTick(timer_id loop.IdType, lp *loop.Loop, callback loop.TimerCallback, do_scroll func(int, *loop.MouseEvent) error) error {
	if !ms.is_active || ms.drag_scroll.timer_id != timer_id || ms.drag_scroll.pixel_gap == 0 {
		return nil
	}
	amt := 1
	if ms.drag_scroll.pixel_gap < 0 {
		amt *= -1
	}
	err := do_scroll(amt, &ms.drag_scroll.mouse_event)
	if err == nil {
		ms.drag_scroll.timer_id, _ = lp.AddTimer(50*time.Millisecond, false, callback)
	}
	return err
}

func (ms *MouseSelection) DragScroll(ev *loop.MouseEvent, lp *loop.Loop, callback loop.TimerCallback) {
	if !ms.is_active {
		return
	}
	upper := ms.min_y * ms.cell_height
	lower := (ms.max_y + 1) * ms.cell_height
	if ev.Pixel.Y < upper {
		ms.drag_scroll.pixel_gap = ev.Pixel.Y - upper
	} else if ev.Pixel.Y > lower {
		ms.drag_scroll.pixel_gap = ev.Pixel.Y - lower
	}
	if ms.drag_scroll.timer_id == 0 && ms.drag_scroll.pixel_gap != 0 {
		ms.drag_scroll.timer_id, _ = lp.AddTimer(50*time.Millisecond, false, callback)
	}
	ms.drag_scroll.mouse_event = *ev
}

type Point struct {
	X, Y int
}

func (p Point) Sub(other Point) Point {
	return Point{X: p.X - other.X, Y: p.Y - other.Y}
}

type CellRegion struct {
	TopLeft, BottomRight Point
	Id                   string
	OnClick              []func(id string) error                                       // simple left click ignoring modifiers
	OnClickEvent         func(id string, ev *loop.MouseEvent, cell_offset Point) error // any click event
	PointerShape         loop.PointerShape
	HoverStyle           string // set to "default" for the global hover style
}

func (c CellRegion) Contains(x, y int) bool { // 0-based
	if c.TopLeft.Y > y || c.BottomRight.Y < y {
		return false
	}
	return (y > c.TopLeft.Y || (y == c.TopLeft.Y && x >= c.TopLeft.X)) && (y < c.BottomRight.Y || (y == c.BottomRight.Y && x <= c.BottomRight.X))
}

type MouseState struct {
	Cell, Pixel Point
	Pressed     struct{ Left, Right, Middle, Fourth, Fifth, Sixth, Seventh bool }

	regions           []*CellRegion
	region_id_map     map[string][]*CellRegion
	region_line_map   map[int][]*CellRegion
	hovered_ids       *utils.Set[string]
	default_url_style struct {
		value  string
		loaded bool
	}
}

func (m *MouseState) add_region(cr CellRegion) *CellRegion {
	m.regions = append(m.regions, &cr)
	if m.region_id_map == nil {
		m.region_id_map = make(map[string][]*CellRegion)
		m.region_line_map = make(map[int][]*CellRegion)
	}
	m.region_id_map[cr.Id] = append(m.region_id_map[cr.Id], &cr)
	for y := cr.TopLeft.Y; y <= cr.BottomRight.Y; y++ {
		m.region_line_map[y] = append(m.region_line_map[y], &cr)
	}
	return &cr
}

func (m *MouseState) AddCellRegion(id string, start_x, start_y, end_x, end_y int, on_click ...func(id string) error) *CellRegion {
	return m.add_region(CellRegion{
		TopLeft: Point{start_x, start_y}, BottomRight: Point{end_x, end_y}, Id: id, OnClick: on_click, PointerShape: loop.POINTER_POINTER, HoverStyle: "default"})
}

func (m *MouseState) ClearCellRegions() {
	m.regions = nil
	m.region_id_map = nil
	m.hovered_ids = nil
	m.region_line_map = nil
}

func (m *MouseState) UpdateHoveredIds() (changed bool) {
	h := utils.NewSet[string]()
	for _, r := range m.region_line_map[m.Cell.Y] {
		if r.Contains(m.Cell.X, m.Cell.Y) {
			h.Add(r.Id)
		}
	}
	changed = !h.Equal(m.hovered_ids)
	m.hovered_ids = h
	return
}

func (m *MouseState) ApplyHoverStyles(lp *loop.Loop, style ...string) {
	if m.hovered_ids == nil || m.hovered_ids.Len() == 0 {
		lp.ClearPointerShapes()
		return
	}
	hs := ""
	if len(style) == 0 {
		if !m.default_url_style.loaded {
			m.default_url_style.loaded = true
			color, style := kitty.DefaultUrlColor, kitty.DefaultUrlStyle
			line_handler := func(key, val string) error {
				switch key {
				case "url_color":
					color = val
				case "url_style":
					style = val
				}
				return nil
			}
			config.ReadKittyConfig(line_handler)
			if style != "none" && style != "" {
				m.default_url_style.value = fmt.Sprintf("u=%s uc=%s", style, color)
			}
		}
		hs = m.default_url_style.value
	} else {
		hs = style[0]
	}
	is_hovered := false
	ps := loop.DEFAULT_POINTER
	for id := range m.hovered_ids.Iterable() {
		for _, r := range m.region_id_map[id] {
			if r.HoverStyle != "" {
				s := strings.Replace(r.HoverStyle, "default", hs, 1)
				lp.StyleRegion(s, r.TopLeft.X, r.TopLeft.Y, r.BottomRight.X, r.BottomRight.Y)
			}
			is_hovered = true
			ps = r.PointerShape
		}
	}
	if is_hovered {
		if s, has := lp.CurrentPointerShape(); !has || s != ps {
			lp.PushPointerShape(ps)
		}
	} else {
		lp.ClearPointerShapes()
	}
}

func (m *MouseState) DispatchEventToHoveredRegions(ev *loop.MouseEvent) error {
	if ev.Event_type != loop.MOUSE_CLICK {
		return nil
	}
	is_simple_click := ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0
	seen := utils.NewSet[string]()
	for id := range m.hovered_ids.Iterable() {
		for _, r := range m.region_id_map[id] {
			if seen.Has(r.Id) {
				continue
			}
			seen.Add(r.Id)
			if is_simple_click {
				for _, f := range r.OnClick {
					if err := f(r.Id); err != nil {
						return err
					}
				}
			}
			if r.OnClickEvent != nil {
				if err := r.OnClickEvent(r.Id, ev, m.Cell.Sub(r.TopLeft)); err != nil {
					return err
				}
			}
		}
	}
	return nil
}

func (m *MouseState) ClickHoveredRegions() error {
	seen := utils.NewSet[string]()
	for id := range m.hovered_ids.Iterable() {
		for _, r := range m.region_id_map[id] {
			if seen.Has(r.Id) {
				continue
			}
			seen.Add(r.Id)
			for _, f := range r.OnClick {
				if err := f(r.Id); err != nil {
					return err
				}
			}
		}
	}
	return nil
}

func (m *MouseState) UpdateState(ev *loop.MouseEvent) (hovered_ids_changed bool) {
	m.Cell = ev.Cell
	m.Pixel = ev.Pixel
	if ev.Event_type == loop.MOUSE_PRESS || ev.Event_type == loop.MOUSE_RELEASE {
		pressed := ev.Event_type == loop.MOUSE_PRESS
		if ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0 {
			m.Pressed.Left = pressed
		}
		if ev.Buttons&loop.RIGHT_MOUSE_BUTTON != 0 {
			m.Pressed.Right = pressed
		}
		if ev.Buttons&loop.MIDDLE_MOUSE_BUTTON != 0 {
			m.Pressed.Middle = pressed
		}
		if ev.Buttons&loop.FOURTH_MOUSE_BUTTON != 0 {
			m.Pressed.Fourth = pressed
		}
		if ev.Buttons&loop.FIFTH_MOUSE_BUTTON != 0 {
			m.Pressed.Fifth = pressed
		}
		if ev.Buttons&loop.SIXTH_MOUSE_BUTTON != 0 {
			m.Pressed.Sixth = pressed
		}
		if ev.Buttons&loop.SEVENTH_MOUSE_BUTTON != 0 {
			m.Pressed.Seventh = pressed
		}
	}
	return m.UpdateHoveredIds()
}
