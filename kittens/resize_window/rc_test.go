// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestResizeCommandEscapeCode(t *testing.T) {
	ec, err := resize_command_escape_code(-4, "vertical")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(ec, "\x1bP@kitty-cmd") || !strings.HasSuffix(ec, "\x1b\\") {
		t.Fatalf("bad framing: %q", ec)
	}
	var cmd struct {
		Cmd     string `json:"cmd"`
		Version [3]int `json:"version"`
		Payload struct {
			Increment int    `json:"increment"`
			Axis      string `json:"axis"`
			Self      bool   `json:"self"`
		} `json:"payload"`
	}
	body := strings.TrimSuffix(strings.TrimPrefix(ec, "\x1bP@kitty-cmd"), "\x1b\\")
	if err := json.Unmarshal([]byte(body), &cmd); err != nil {
		t.Fatal(err)
	}
	if cmd.Cmd != "resize-window" || cmd.Payload.Increment != -4 || cmd.Payload.Axis != "vertical" || !cmd.Payload.Self {
		t.Fatalf("bad command: %+v", cmd)
	}
	if cmd.Version == [3]int{} {
		t.Fatal("version not set")
	}
}
