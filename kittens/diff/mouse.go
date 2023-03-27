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
	line ScrollPos
	x    int
}

type MouseSelection struct {
	start, end   SelectionBoundary
	is_active    bool
	min_x, max_x int
}

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
	ms.end.line = pos
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

func (self *Handler) add_mouse_selection_to_line(line string, line_pos ScrollPos) {
	ms := &self.mouse_selection
	if !ms.is_active {
		return
	}
}
