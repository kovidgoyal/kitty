// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"

	"kitty/tools/tui/loop"
)

var _ = fmt.Print

func (self *Readline) handle_key_event(event *loop.KeyEvent) error {
	if event.Text != "" {
		return nil
	}
	return nil
}
