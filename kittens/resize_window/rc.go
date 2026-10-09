// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"encoding/json"

	"github.com/kovidgoyal/kitty/tools/cmd/at"
	"github.com/kovidgoyal/kitty/tools/utils"
)

type resize_payload struct {
	Increment int     `json:"increment"`
	Axis      string  `json:"axis"`
	Self      bool    `json:"self"`
	Fraction  float64 `json:"fraction,omitempty"`
	Restore   bool    `json:"restore_entry_layout,omitempty"`
}

func resize_command_escape_code(increment int, axis string, fraction float64) (string, error) {
	restore := axis == "restore"
	if restore {
		axis = "reset"
	}
	rc := utils.RemoteControlCmd{
		Cmd: "resize-window", Version: at.ProtocolVersion,
		Payload: resize_payload{Increment: increment, Axis: axis, Self: true, Fraction: fraction, Restore: restore},
	}
	data, err := json.Marshal(rc)
	if err != nil {
		return "", err
	}
	return "\x1bP@kitty-cmd" + string(data) + "\x1b\\", nil
}

func edge_command_escape_code(operation, edge, divider string, increment int, fraction float64) (string, error) {
	rc := utils.RemoteControlCmd{
		Cmd: "resize-window-edge", Version: at.ProtocolVersion,
		Payload: struct {
			Operation string  `json:"operation"`
			Edge      string  `json:"edge"`
			Divider   string  `json:"divider,omitempty"`
			Increment int     `json:"increment"`
			Fraction  float64 `json:"fraction,omitempty"`
			Self      bool    `json:"self"`
		}{operation, edge, divider, increment, fraction, true},
	}
	data, err := json.Marshal(rc)
	if err != nil {
		return "", err
	}
	return "\x1bP@kitty-cmd" + string(data) + "\x1b\\", nil
}
