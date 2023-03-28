// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"path/filepath"
	"strconv"

	"kitty"
	"kitty/tools/config"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
)

var _ = fmt.Print

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

	min_x := self.logical_lines.margin_size
	max_x := available_cols - 1
	if ev.Cell.X >= available_cols {
		min_x += available_cols
		max_x += available_cols
	}
	self.mouse_selection.StartNewSelection(ev, &pos, min_x, max_x, 0, self.screen_size.num_lines-1, self.screen_size.cell_width, self.screen_size.cell_height)
}

func (self *Handler) update_mouse_selection(ev *loop.MouseEvent) {
	if !self.mouse_selection.IsActive() {
		return
	}
	pos := self.scroll_pos
	y := ev.Cell.Y
	y = utils.Max(0, utils.Min(y, self.screen_size.num_lines-1))
	self.logical_lines.IncrementScrollPosBy(&pos, y)
	self.mouse_selection.Update(ev, &pos)
	self.draw_screen()
}

func (self *Handler) clear_mouse_selection() {
	self.mouse_selection.Clear()
}

func (self *Handler) finish_mouse_selection(ev *loop.MouseEvent) {
	if !self.mouse_selection.IsActive() {
		return
	}
	self.update_mouse_selection(ev)
	self.mouse_selection.Finish()
}

func (self *Handler) add_mouse_selection_to_line(line string, line_pos ScrollPos, y int) string {
	return line + self.mouse_selection.LineFormatSuffix(&line_pos, selection_sgr, y)
}
