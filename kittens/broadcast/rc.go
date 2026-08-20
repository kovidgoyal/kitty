// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package broadcast

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"

	"github.com/kovidgoyal/kitty/tools/cmd/at"
	"github.com/kovidgoyal/kitty/tools/utils"
)

type broadcast_payload struct {
	ExcludeActive bool   `json:"exclude_active"`
	Data          string `json:"data"`
	Match         string `json:"match,omitempty"`
	MatchTab      string `json:"match_tab,omitempty"`
	SessionId     string `json:"session_id"`
	All           bool   `json:"all,omitempty"`
}

func send_text_escape_code(p broadcast_payload) (string, error) {
	rc := utils.RemoteControlCmd{Cmd: "send-text", Version: at.ProtocolVersion, NoResponse: true, Payload: p}
	data, err := json.Marshal(rc)
	if err != nil {
		return "", err
	}
	return "\x1bP@kitty-cmd" + string(data) + "\x1b\\", nil
}

func session_escape_code(p broadcast_payload, start bool) (string, error) {
	if start {
		p.Data = "session:start"
	} else {
		p.Data = "session:end"
	}
	return send_text_escape_code(p)
}

func new_session_id() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}
