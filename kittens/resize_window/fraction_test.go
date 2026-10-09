// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"encoding/json"
	"math"
	"strings"
	"testing"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

func TestResizeFractionParsing(t *testing.T) {
	for value, want := range map[string]float64{"1/3": 1.0 / 3, "1/4": 0.25, "0.5": 0.5, "1": 1, "2/6": 1.0 / 3, " 1 / 3 ": 1.0 / 3} {
		got, err := parse_fraction(value)
		if err != nil || math.Abs(got-want) > 1e-12 {
			t.Fatalf("%q: got %v, %v; want %v", value, got, err, want)
		}
	}
	for _, value := range []string{"", "0", "-1", "1.1", "4/3", "1/0", "-1/-3", "1/-3", "1/NaN", "1/Inf", "NaN", "Inf", "1/2/3", "abc"} {
		if _, err := parse_fraction(value); err == nil {
			t.Fatalf("accepted invalid fraction %q", value)
		}
	}
}

func TestResizeFractionKeys(t *testing.T) {
	for _, key := range []string{"w", "n", "t", "s"} {
		for _, mods := range []loop.KeyModifiers{0, loop.SHIFT, loop.CTRL, loop.ALT} {
			for _, eventType := range []loop.KeyEventType{loop.PRESS, loop.REPEAT, loop.RELEASE} {
				h := &handler{lp: &loop.Loop{}, opts: &Options{HorizontalIncrement: 2, VerticalIncrement: 2}, fraction: 1.0 / 3}
				e := &loop.KeyEvent{Key: key, Mods: mods, Type: eventType}
				if err := h.on_key(e); err != nil || !e.Handled {
					t.Fatalf("%s mods=%v type=%v: handled=%v error=%v", key, mods, eventType, e.Handled, err)
				}
			}
		}
	}
}

func TestResizeFractionPayload(t *testing.T) {
	for _, fraction := range []float64{0, 1.0 / 3, 1} {
		ec, err := resize_command_escape_code(2, "horizontal", fraction)
		if err != nil {
			t.Fatal(err)
		}
		var cmd struct {
			Payload map[string]json.RawMessage `json:"payload"`
		}
		body := strings.TrimSuffix(strings.TrimPrefix(ec, "\x1bP@kitty-cmd"), "\x1b\\")
		if err := json.Unmarshal([]byte(body), &cmd); err != nil {
			t.Fatal(err)
		}
		raw, present := cmd.Payload["fraction"]
		if present != (fraction != 0) {
			t.Fatalf("fraction %v: unexpected presence %v", fraction, present)
		}
		if present {
			var got float64
			if err := json.Unmarshal(raw, &got); err != nil || got != fraction {
				t.Fatalf("fraction %v: got %s, %v", fraction, raw, err)
			}
		}
	}
}
