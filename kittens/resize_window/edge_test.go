// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

func TestEdgeResizeKeys(t *testing.T) {
	for _, modifier := range []string{"alt", "shift"} {
		for _, key := range []string{"h", "j", "k", "l", "LEFT", "RIGHT", "UP", "DOWN"} {
			for _, mods := range []loop.KeyModifiers{0, loop.SHIFT, loop.CTRL, loop.ALT, loop.CTRL | loop.SHIFT} {
				for _, typ := range []loop.KeyEventType{loop.PRESS, loop.REPEAT, loop.RELEASE} {
					settings := default_settings()
					settings.Strategy = "edge"
					settings.Strategies["edge"] = strategy_settings{modifier, "1/4"}
					h := &handler{lp: &loop.Loop{}, opts: &Options{Strategy: "edge", HorizontalIncrement: 3, VerticalIncrement: 2}, settings: settings, fraction: 0.25, edge_pending: true}
					e := &loop.KeyEvent{Key: key, Mods: mods, Type: typ}
					if err := h.on_key(e); err != nil || !e.Handled {
						t.Fatalf("%s mods=%v type=%v: handled=%v err=%v", key, mods, typ, e.Handled, err)
					}
					if typ == loop.RELEASE || mods == loop.CTRL|loop.SHIFT {
						if len(h.edge_queue) != 0 {
							t.Fatal("release or unsupported modifiers produced an action")
						}
						continue
					}
					if len(h.edge_queue) != 1 {
						t.Fatal("key did not queue exactly one action")
					}
					input := h.edge_queue[0]
					fraction, multiplier := 0.0, 1
					if (modifier == "alt" && mods == loop.ALT) || (modifier == "shift" && mods == loop.SHIFT) {
						fraction = 0.25
					}
					if mods == loop.CTRL {
						multiplier = 2
					}
					if input.fraction != fraction || input.multiplier != multiplier {
						t.Fatalf("%s mods=%v: got %+v", key, mods, input)
					}
				}
			}
		}
	}
}

func TestEdgeSettingsCancelQueuedMoves(t *testing.T) {
	lp, err := loop.New()
	if err != nil {
		t.Fatal(err)
	}
	settings := default_settings()
	settings.Strategy = "edge"
	h := &handler{lp: lp, ctx: markup.New(true), opts: &Options{HorizontalIncrement: 2}, settings: settings, edge_ready: true, edge_pending: true}
	if err := h.on_text("l"); err != nil || len(h.edge_queue) != 1 {
		t.Fatalf("key was not queued: %v", err)
	}
	if err := h.on_text("f"); err != nil || len(h.edge_queue) != 0 || h.page != "fraction" {
		t.Fatalf("settings did not cancel queued movement: %v", err)
	}
	state, _ := json.Marshal(edge_state{Edges: []string{"right"}, Selected: "right", Divider: "123"})
	raw, _ := json.Marshal(string(state))
	response, _ := json.Marshal(rc_response{Ok: true, Data: raw})
	if err := h.on_rc_response(response); err != nil || h.edge_pending {
		t.Fatalf("reply while editing settings: %v", err)
	}
	e := &loop.KeyEvent{Key: "ESCAPE", Type: loop.PRESS}
	if err := h.on_key(e); err != nil || h.page != "" || len(h.edge_queue) != 0 || h.edge_pending {
		t.Fatalf("closing settings replayed canceled keys: %v", err)
	}
	if h.edge_state.Selected != "right" {
		t.Fatal("settings lost the selected edge")
	}
}

func TestEdgeLateResponseAfterStrategySwitch(t *testing.T) {
	lp, err := loop.New()
	if err != nil {
		t.Fatal(err)
	}
	h := &handler{lp: lp, ctx: markup.New(true), settings: default_settings(), edge_pending: true, edge_queue: []edge_input{{key: "l", multiplier: 1}}}
	state, _ := json.Marshal(edge_state{Edges: []string{"right"}, Selected: "right", Divider: "123"})
	raw, _ := json.Marshal(string(state))
	response, _ := json.Marshal(rc_response{Ok: true, Data: raw})
	if err := h.on_rc_response(response); err != nil || len(h.edge_queue) != 0 || h.edge_pending {
		t.Fatalf("late edge reply was not consumed: %v", err)
	}
	if h.active_strategy() != "window" {
		t.Fatal("late edge reply changed the active strategy")
	}
}

func TestEdgeResizeSelectBeforeQueuedMove(t *testing.T) {
	lp, err := loop.New()
	if err != nil {
		t.Fatal(err)
	}
	settings := default_settings()
	settings.Strategy = "edge"
	h := &handler{lp: lp, opts: &Options{Strategy: "edge", HorizontalIncrement: 2}, settings: settings, edge_ready: true}
	if err := h.on_text("l"); err != nil || !h.edge_pending {
		t.Fatalf("first key did not select: %v", err)
	}
	if err := h.on_text("h"); err != nil || len(h.edge_queue) != 1 {
		t.Fatalf("second key did not wait for selection: %v", err)
	}
	state, _ := json.Marshal(edge_state{Edges: []string{"right"}, Selected: "right", Divider: "123"})
	raw, _ := json.Marshal(string(state))
	if err := h.on_edge_response(raw); err != nil || !h.edge_pending || len(h.edge_queue) != 0 {
		t.Fatalf("queued move did not run after selection: %v", err)
	}
	if h.edge_state.Selected != "right" || h.edge_state.Divider != "123" {
		t.Fatal("selection identity was lost")
	}
}

func TestEdgeResizePayload(t *testing.T) {
	ec, err := edge_command_escape_code("move", "left", "123", -3, 0.25)
	if err != nil {
		t.Fatal(err)
	}
	var cmd struct {
		Cmd     string `json:"cmd"`
		Payload struct {
			Operation string  `json:"operation"`
			Edge      string  `json:"edge"`
			Divider   string  `json:"divider"`
			Increment int     `json:"increment"`
			Fraction  float64 `json:"fraction"`
			Self      bool    `json:"self"`
		} `json:"payload"`
	}
	body := strings.TrimSuffix(strings.TrimPrefix(ec, "\x1bP@kitty-cmd"), "\x1b\\")
	if err := json.Unmarshal([]byte(body), &cmd); err != nil {
		t.Fatal(err)
	}
	p := cmd.Payload
	if cmd.Cmd != "resize-window-edge" || p.Operation != "move" || p.Edge != "left" || p.Divider != "123" || p.Increment != -3 || p.Fraction != 0.25 || !p.Self {
		t.Fatalf("unexpected edge command: %+v", cmd)
	}
}

func TestEdgeStatusReplacesOlderLocalStatus(t *testing.T) {
	lp, err := loop.New()
	if err != nil {
		t.Fatal(err)
	}
	settings := default_settings()
	settings.Strategy = "edge"
	h := &handler{lp: lp, ctx: markup.New(true), opts: &Options{}, settings: settings, edge_pending: true, status: "Could not load settings: bad"}
	state, _ := json.Marshal(edge_state{Edges: []string{"right"}})
	if err := h.on_edge_response(must_marshal(t, string(state))); err != nil || h.status == "" {
		t.Fatalf("a reply without a status cleared the local status: %v", err)
	}
	state, _ = json.Marshal(edge_state{Edges: []string{"right"}, Selected: "right", Status: "At size limit; move the other way", Failed: true})
	if err := h.on_edge_response(must_marshal(t, string(state))); err != nil || h.status != "" || !h.edge_state.Failed {
		t.Fatalf("a newer edge status was hidden by an older local status: %q %v", h.status, err)
	}
}

func must_marshal(t *testing.T, v any) json.RawMessage {
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}
