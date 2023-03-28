// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"kitty"
	"kitty/tools/config"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"path/filepath"
	"strconv"
)

var _ = fmt.Print

type SelectionBoundary struct {
	line                  ScrollPos
	x                     int
	in_first_half_of_cell bool
}

type MouseSelection struct {
	start, end   SelectionBoundary
	is_active    bool
	min_x, max_x int
}

func (self *MouseSelection) IsEmpty() bool { return self.start == self.end }

type KittyOpts struct {
	Wheel_scroll_multiplier int
}

func read_relevant_kitty_opts(path string) KittyOpts {
	ans := KittyOpts{Wheel_scroll_multiplier: kitty.KittyConfigDefaults.Wheel_scroll_multiplier}
	handle_line := func(key, val string) error {
		switch key {
		case "wheel_scroll_multiplier":
			v, err := strconv.Atoi(val)
			if err == nil {
				ans.Wheel_scroll_multiplier = v
			}
		}
		return nil
	}
	cp := config.ConfigParser{LineHandler: handle_line}
	cp.ParseFiles(path)
	return ans
}

var RelevantKittyOpts = (&utils.Once[KittyOpts]{Run: func() KittyOpts {
	return read_relevant_kitty_opts(filepath.Join(utils.ConfigDir(), "kitty.conf"))
}}).Get

func (self *Handler) handle_wheel_event(up bool) {
	amt := RelevantKittyOpts().Wheel_scroll_multiplier
	if up {
		amt *= -1
	}
	self.dispatch_action(`scroll_by`, strconv.Itoa(amt))
}

func (self *Handler) start_mouse_selection(ev *loop.MouseEvent) {
	self.mouse_selection = MouseSelection{}
	ms := &self.mouse_selection
	available_cols := self.logical_lines.columns / 2
	if ev.Cell.Y >= self.screen_size.num_lines || ev.Cell.X < self.logical_lines.margin_size || (ev.Cell.X >= available_cols && ev.Cell.X < available_cols+self.logical_lines.margin_size) {
		return
	}
	pos := self.scroll_pos
	self.logical_lines.IncrementScrollPosBy(&pos, ev.Cell.Y)
	ll := self.logical_lines.At(pos.logical_line)
	if ll.line_type == EMPTY_LINE || ll.line_type == IMAGE_LINE {
		return
	}
	ms.start.line = pos

	ms.start.x = ev.Cell.X
	ms.min_x = self.logical_lines.margin_size
	ms.max_x = available_cols - 1
	if ms.start.x >= available_cols {
		ms.min_x += available_cols
		ms.max_x += available_cols
	}
	ms.start.x = utils.Max(ms.min_x, utils.Min(ms.start.x, ms.max_x))
	cell_start := self.screen_size.cell_width * ev.Cell.X
	ms.start.in_first_half_of_cell = ev.Pixel.X <= cell_start+self.screen_size.cell_width/2

	ms.end = ms.start
	ms.is_active = true
}

func (self *Handler) update_mouse_selection(ev *loop.MouseEvent) {
	ms := &self.mouse_selection
	if !self.mouse_selection.is_active {
		return
	}
	pos := self.scroll_pos
	y := ev.Cell.Y
	y = utils.Max(0, utils.Min(y, self.screen_size.num_lines-1))
	self.logical_lines.IncrementScrollPosBy(&pos, y)
	ms.end.x = ev.Cell.X
	ms.end.x = utils.Max(ms.min_x, utils.Min(ms.end.x, ms.max_x))
	cell_start := self.screen_size.cell_width * ms.end.x
	ms.end.in_first_half_of_cell = ev.Pixel.X <= cell_start+self.screen_size.cell_width/2
	ms.end.line = pos
	self.draw_screen()
}

func (self *Handler) clear_mouse_selection() {
	self.mouse_selection = MouseSelection{}
}

func (self *Handler) finish_mouse_selection(ev *loop.MouseEvent) {
	self.update_mouse_selection(ev)
	ms := &self.mouse_selection
	if !self.mouse_selection.is_active {
		return
	}
	ms.is_active = false
}

func format_part_of_line(sgr string, start_x, end_x, y int) string {
	// DECCARA used to set formatting in specified region using zero based indexing
	return fmt.Sprintf("\x1b[%d;%d;%d;%d;%s$r", y+1, start_x+1, y+1, end_x+1, sgr)
}

func (self *Handler) add_mouse_selection_to_line(line string, line_pos ScrollPos, y int) string {
	ms := &self.mouse_selection
	if ms.IsEmpty() {
		return line
	}
	a, b := ms.start.line, ms.end.line
	ax, bx := ms.start.x, ms.end.x
	if b.Less(a) {
		a, b = b, a
		ax, bx = bx, ax
	}
	if a.Less(line_pos) {
		if line_pos.Less(b) {
			line += format_part_of_line(selection_sgr, 0, ms.max_x, y)
		} else if b == line_pos {
			line += format_part_of_line(selection_sgr, 0, bx, y)
		}
	} else if a == line_pos {
		if line_pos.Less(b) {
			line += format_part_of_line(selection_sgr, ax, ms.max_x, y)
		} else if b == line_pos {
			line += format_part_of_line(selection_sgr, ax, bx, y)
		}
	}
	return line
}
