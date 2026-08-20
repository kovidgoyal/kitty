// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package broadcast

import (
	"encoding/json"
	"strings"
	"testing"
)

func decode(t *testing.T, ec string) map[string]any {
	t.Helper()
	if !strings.HasPrefix(ec, "\x1bP@kitty-cmd") || !strings.HasSuffix(ec, "\x1b\\") {
		t.Fatalf("bad framing: %q", ec)
	}
	body := strings.TrimSuffix(strings.TrimPrefix(ec, "\x1bP@kitty-cmd"), "\x1b\\")
	var m map[string]any
	if err := json.Unmarshal([]byte(body), &m); err != nil {
		t.Fatal(err)
	}
	return m
}

func TestSendTextEscapeCode(t *testing.T) {
	p := broadcast_payload{ExcludeActive: true, Data: "base64:aGk=", SessionId: "abc", All: true}
	ec, err := send_text_escape_code(p)
	if err != nil {
		t.Fatal(err)
	}
	m := decode(t, ec)
	if m["cmd"] != "send-text" || m["no_response"] != true {
		t.Fatalf("bad cmd: %v", m)
	}
	payload := m["payload"].(map[string]any)
	if payload["data"] != "base64:aGk=" || payload["exclude_active"] != true || payload["all"] != true || payload["session_id"] != "abc" {
		t.Fatalf("bad payload: %v", payload)
	}
	if _, has := payload["match"]; has {
		t.Fatal("empty match should be omitted")
	}
}

func TestSessionEscapeCode(t *testing.T) {
	p := broadcast_payload{SessionId: "abc"}
	ec, err := session_escape_code(p, false)
	if err != nil {
		t.Fatal(err)
	}
	payload := decode(t, ec)["payload"].(map[string]any)
	if payload["data"] != "session:end" {
		t.Fatalf("bad session data: %v", payload)
	}
}

func TestNewSessionId(t *testing.T) {
	a, b := new_session_id(), new_session_id()
	if a == b || len(a) != 32 {
		t.Fatalf("bad session ids: %q %q", a, b)
	}
}
