// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"strconv"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type KittyOpts struct {
	Wheel_scroll_multiplier int
	Copy_on_select          bool
}

func read_relevant_kitty_opts() KittyOpts {
	ans := KittyOpts{Wheel_scroll_multiplier: kitty.KittyConfigDefaults.Wheel_scroll_multiplier}
	handle_line := func(key, val string) error {
		switch key {
		case "wheel_scroll_multiplier":
			v, err := strconv.Atoi(val)
			if err == nil {
				ans.Wheel_scroll_multiplier = v
			}
		case "copy_on_select":
			ans.Copy_on_select = strings.ToLower(val) == "clipboard"
		}
		return nil
	}
	config.ReadKittyConfig(handle_line)
	return ans
}

var RelevantKittyOpts = sync.OnceValue(func() KittyOpts {
	return read_relevant_kitty_opts()
})

func (self *Handler) handle_wheel_event(up bool) {
	amt := RelevantKittyOpts().Wheel_scroll_multiplier
	if up {
		amt *= -1
	}
	_ = self.dispatch_action(`scroll_by`, strconv.Itoa(amt))
}

type line_pos struct {
	min_x, max_x int
	y            ScrollPos
}

func (self *line_pos) MinX() int { return self.min_x }
func (self *line_pos) MaxX() int { return self.max_x }
func (self *line_pos) Equal(other tui.LinePos) bool {
	if o, ok := other.(*line_pos); ok {
		return self.y == o.y
	}
	return false
}

func (self *line_pos) LessThan(other tui.LinePos) bool {
	if o, ok := other.(*line_pos); ok {
		return self.y.Less(o.y)
	}
	return false
}

func (self *Handler) line_pos_from_pos(x int, pos ScrollPos) *line_pos {
	ans := line_pos{min_x: self.logical_lines.margin_size, y: pos}
	available_cols := self.logical_lines.columns / 2
	if x >= available_cols {
		ans.min_x += available_cols
		ans.max_x = utils.Max(ans.min_x, ans.min_x+self.logical_lines.ScreenLineAt(pos).right.wcswidth()-1)
	} else {
		ans.max_x = utils.Max(ans.min_x, ans.min_x+self.logical_lines.ScreenLineAt(pos).left.wcswidth()-1)
	}
	return &ans
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
	self.mouse_selection.StartNewSelection(ev, self.line_pos_from_pos(ev.Cell.X, pos), 0, self.screen_size.num_lines-1, self.screen_size.cell_width, self.screen_size.cell_height)
}

func (self *Handler) drag_scroll_tick(timer_id loop.IdType) error {
	return self.mouse_selection.DragScrollTick(timer_id, self.lp, self.drag_scroll_tick, func(amt int, ev *loop.MouseEvent) error {
		if self.scroll_lines(amt) != 0 {
			self.do_update_mouse_selection(ev)
			self.draw_screen()
		}
		return nil
	})
}

var debugprintln = tty.DebugPrintln

func (self *Handler) update_mouse_selection(ev *loop.MouseEvent) {
	if !self.mouse_selection.IsActive() {
		return
	}
	if self.mouse_selection.OutOfVerticalBounds(ev) {
		self.mouse_selection.DragScroll(ev, self.lp, self.drag_scroll_tick)
		return
	}
	self.do_update_mouse_selection(ev)
}

func (self *Handler) do_update_mouse_selection(ev *loop.MouseEvent) {
	pos := self.scroll_pos
	y := ev.Cell.Y
	y = utils.Max(0, utils.Min(y, self.screen_size.num_lines-1))
	self.logical_lines.IncrementScrollPosBy(&pos, y)
	x := self.mouse_selection.StartLine().MinX()
	self.mouse_selection.Update(ev, self.line_pos_from_pos(x, pos))
	self.draw_screen()
}

func (self *Handler) clear_mouse_selection() {
	self.mouse_selection.Clear()
}

func (self *Handler) text_for_current_mouse_selection() string {
	if self.mouse_selection.IsEmpty() {
		return ""
	}
	text := make([]byte, 0, 2048)
	start_pos, end_pos := *self.mouse_selection.StartLine().(*line_pos), *self.mouse_selection.EndLine().(*line_pos)

	// if start is after end, swap them
	if end_pos.y.Less(start_pos.y) {
		start_pos, end_pos = end_pos, start_pos
	}

	start, end := start_pos.y, end_pos.y
	is_left := start_pos.min_x == self.logical_lines.margin_size

	line_for_pos := func(pos ScrollPos) string {
		if is_left {
			return self.logical_lines.ScreenLineAt(pos).left.marked_up_text
		}
		return self.logical_lines.ScreenLineAt(pos).right.marked_up_text
	}

	for pos, prev_ll_idx := start, start.logical_line; pos.Less(end) || pos == end; {
		ll := self.logical_lines.At(pos.logical_line)
		var line string
		switch ll.line_type {
		case EMPTY_LINE:
		case IMAGE_LINE:
			if pos.screen_line < ll.image_lines_offset {
				line = line_for_pos(pos)
			}
		default:
			line = line_for_pos(pos)
		}
		line = wcswidth.StripEscapeCodes(line)
		s, e := self.mouse_selection.LineBounds(self.line_pos_from_pos(start_pos.min_x, pos))
		s -= start_pos.min_x
		e -= start_pos.min_x
		line = wcswidth.TruncateToVisualLength(line, e+1)
		if s > 0 {
			prefix := wcswidth.TruncateToVisualLength(line, s)
			line = line[len(prefix):]
		}
		// TODO: look at the original line from the source and handle leading tabs as per it
		if pos.logical_line > prev_ll_idx {
			line = "\n" + line
		}
		prev_ll_idx = pos.logical_line
		if line != "" {
			text = append(text, line...)
		}
		if self.logical_lines.IncrementScrollPosBy(&pos, 1) == 0 {
			break
		}
	}
	return utils.UnsafeBytesToString(text)
}

func (self *Handler) finish_mouse_selection(ev *loop.MouseEvent) {
	if !self.mouse_selection.IsActive() {
		return
	}
	self.update_mouse_selection(ev)
	self.mouse_selection.Finish()
	text := self.text_for_current_mouse_selection()
	if text != "" {
		if RelevantKittyOpts().Copy_on_select {
			self.lp.CopyTextToClipboard(text)
		} else {
			self.lp.CopyTextToPrimarySelection(text)
		}
	}
}

func (self *Handler) add_mouse_selection_to_line(line_pos ScrollPos, y int) string {
	if self.mouse_selection.IsEmpty() {
		return ""
	}
	selection_sgr := format_as_sgr.selection
	x := self.mouse_selection.StartLine().MinX()
	return self.mouse_selection.LineFormatSuffix(self.line_pos_from_pos(x, line_pos), selection_sgr[2:len(selection_sgr)-1], y)
}
