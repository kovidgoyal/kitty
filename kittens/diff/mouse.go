// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"path/filepath"
	"strconv"
	"strings"

	"kitty"
	"kitty/tools/config"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"kitty/tools/wcswidth"
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

func (self *Handler) text_for_current_mouse_selection() string {
	if self.mouse_selection.IsEmpty() {
		return ""
	}
	text := make([]byte, 0, 2048)
	start, end := *self.mouse_selection.StartLine().(*ScrollPos), *self.mouse_selection.EndLine().(*ScrollPos)
	for pos, prev_ll_idx := start, start.logical_line; pos.Less(end) || pos.Equal(&end); self.logical_lines.IncrementScrollPosBy(&pos, 1) {
		ll := self.logical_lines.At(pos.logical_line)
		var line string
		switch ll.line_type {
		case EMPTY_LINE:
		case IMAGE_LINE:
			if pos.screen_line < ll.image_lines_offset {
				line = self.logical_lines.ScreenLineAt(pos)
			}
		default:
			line = self.logical_lines.ScreenLineAt(pos)
		}
		line = wcswidth.StripEscapeCodes(line)
		s, e := self.mouse_selection.LineBounds(&pos)
		line = wcswidth.TruncateToVisualLength(line, e+1)
		if s > 0 {
			prefix := wcswidth.TruncateToVisualLength(line, s)
			line = line[len(prefix):]
		}
		// TODO: look at the original line from the source and handle leading tabs and trailing spaces as per it
		tline := strings.TrimRight(line, " ")
		if len(tline) < len(line) {
			line = tline + " "
		}
		if pos.logical_line > prev_ll_idx {
			line = "\n" + line
		}
		prev_ll_idx = pos.logical_line
		if line != "" {
			text = append(text, line...)
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
		self.lp.CopyTextToPrimarySelection(text)
	}
}

func (self *Handler) add_mouse_selection_to_line(line string, line_pos ScrollPos, y int) string {
	return line + self.mouse_selection.LineFormatSuffix(&line_pos, selection_sgr, y)
}
