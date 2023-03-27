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

type MouseSelection struct {
	start_line, end_line ScrollPos
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
}

func (self *Handler) update_mouse_selection(ev *loop.MouseEvent) {
}

func (self *Handler) finish_mouse_selection(ev *loop.MouseEvent) {
}
