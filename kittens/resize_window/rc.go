// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"encoding/json"

	"github.com/kovidgoyal/kitty/tools/cmd/at"
	"github.com/kovidgoyal/kitty/tools/utils"
)

type resize_payload struct {
	Increment int    `json:"increment"`
	Axis      string `json:"axis"`
	Self      bool   `json:"self"`
}

func resize_command_escape_code(increment int, axis string) (string, error) {
	rc := utils.RemoteControlCmd{
		Cmd: "resize-window", Version: at.ProtocolVersion,
		Payload: resize_payload{Increment: increment, Axis: axis, Self: true},
	}
	data, err := json.Marshal(rc)
	if err != nil {
		return "", err
	}
	return "\x1bP@kitty-cmd" + string(data) + "\x1b\\", nil
}
