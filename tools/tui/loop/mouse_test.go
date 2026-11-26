// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
)

func TestDecodeDetailedMouseEvent(t *testing.T) {
	sz := ScreenSize{WidthPx: 1000, HeightPx: 500, CellWidth: 10, CellHeight: 20}
	ev := func(etype MouseEventType, serial uint32, x, y, px, py int, held MouseButtonFlag, mods KeyModifiers, ts time.Duration) *MouseEvent {
		ans := &MouseEvent{Event_type: etype, Detailed: true, Serial: serial, HeldButtons: held, Mods: mods, Timestamp: ts}
		ans.Cell.X, ans.Cell.Y = x, y
		ans.Pixel.X, ans.Pixel.Y = px, py
		return ans
	}
	press := ev(MOUSE_PRESS, 101, 9, 4, 95, 83, LEFT_MOUSE_BUTTON, 0, 4*time.Second+16000*time.Microsecond)
	press.Buttons, press.ClickCount = LEFT_MOUSE_BUTTON, 1
	release := ev(MOUSE_RELEASE, 104, 0, 4, -30, 83, NO_MOUSE_BUTTON, 0, 4*time.Second+52110*time.Microsecond)
	release.Buttons, release.ClickCount = LEFT_MOUSE_BUTTON, 1
	double := ev(MOUSE_PRESS, 109, 9, 4, 95, 83, RIGHT_MOUSE_BUTTON, CTRL, 7*time.Second+350000*time.Microsecond)
	double.Buttons, double.ClickCount = RIGHT_MOUSE_BUTTON, 2
	drag := ev(MOUSE_MOVE, 103, 0, 4, -7, 83, LEFT_MOUSE_BUTTON|RIGHT_MOUSE_BUTTON, 0, 0)
	drag.Buttons = drag.HeldButtons
	back := ev(MOUSE_PRESS, 1, 0, 0, 0, 0, FOURTH_MOUSE_BUTTON, 0, 0)
	back.Buttons, back.ClickCount = FOURTH_MOUSE_BUTTON, 1
	wheel := func(serial uint32, ts time.Duration, w WheelEvent) *MouseEvent {
		ans := ev(MOUSE_WHEEL, serial, 9, 4, 95, 83, NO_MOUSE_BUTTON, 0, ts)
		ans.Wheel = w
		return ans
	}
	for csi, expected := range map[string]*MouseEvent{
		// The examples from the specification
		">1:101;10;5;95;83;1;1;4:16000;1;1M":  press,
		">2:104;1;5;30:1;83;0;1;4:52110;1;1M": release,
		">1:109;10;5;95;83;4;5;7:350000;3;2M": double,
		">5:106;1;5;2:1;83;0;1;5:300000M":     ev(MOUSE_ENTER, 106, 0, 4, -2, 83, NO_MOUSE_BUTTON, 0, 5*time.Second+300000*time.Microsecond),
		">6:117;10;5;95;83;0;1;15:0M":         ev(MOUSE_LEAVE, 117, 9, 4, 95, 83, NO_MOUSE_BUTTON, 0, 15*time.Second),
		">4:111;10;5;95;83;0;1;9:520000;0;120;1:5000;1;0;0M": wheel(111, 9*time.Second+520000*time.Microsecond, WheelEvent{
			DY: 120, Unit: WHEEL_UNIT_V120, Multiplier: 5, Source: WHEEL_SOURCE_WHEEL}),
		">4:114;10;5;95;83;0;1;12:8453;3;42:1;2:1000;2;2;0M": wheel(114, 12*time.Second+8453*time.Microsecond, WheelEvent{
			DX: 3, DY: -42, Unit: WHEEL_UNIT_PIXELS, Multiplier: 1, Source: WHEEL_SOURCE_FINGER, Phase: WHEEL_PHASE_CHANGED}),
		">4:116;10;5;95;83;0;1;0:0;0;35:1;2;2;1;3M": wheel(116, 0, WheelEvent{
			DY: -35, Unit: WHEEL_UNIT_PIXELS, Source: WHEEL_SOURCE_FINGER, Phase: WHEEL_PHASE_BEGAN, Momentum: true, Inverted: true}),
		// Motion with several buttons held, an explicitly positive value
		">3:103;1;5;7:1;83:0;5;1;0:0M": drag,
		// Buttons are numbered from one, 4 is back
		">1:1;1;1;0;0;8;1;0:0;4;1M": back,
		// Unknown parameters, sub-parameters and types of events are ignored
		">1:101:9;10:3;5;95;83:0:7;1;1;4:16000:5;1;1;77M": press,
		">7:1;1;1;0;0;0;1;0:0M":                           nil,
		// Numbers up to 32 bits
		">3:4294967295;1;1;4294967295;0;0;1;0:0M": ev(MOUSE_MOVE, 4294967295, 0, 0, 4294967295, 0, NO_MOUSE_BUTTON, 0, 0),
		// Malformed events
		">3:4294967296;1;1;0;0;0;1;0:0M":    nil,
		">3:1;1;1;0;0;0;1;0M":               nil,
		">3:1;1;1;0;0;0;1;0:1000000M":       nil,
		">3:1;1;1;-5;0;0;1;0:0M":            nil,
		">3:1;1;1;;0;0;1;0:0M":              nil,
		">3;1;1;0;0;0;1;0:0M":               nil,
		">1:1;1;1;0;0;1;1;0:0;1M":           nil,
		">4:1;1;1;0;0;0;1;0:0;0;120;1;1;0M": nil,
		">3:1;1;1;0;0;0;1M":                 nil,
		">3:1;1;1;0;0;0;1;0:0m":             nil,
		// Legacy encodings are still decoded
		"<64;45;65M": {Buttons: MOUSE_WHEEL_UP, Pixel: struct{ X, Y int }{45, 65}, Cell: struct{ X, Y int }{4, 3}},
	} {
		actual := MouseEventFromCSI(csi, sz)
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed to decode %#v:\n%s", csi, diff)
		}
	}
	// Lines conversion uses the multiplier when present
	w := WheelEvent{DY: 240, Unit: WHEEL_UNIT_V120, Multiplier: 5}
	if _, dy := w.Lines(20, 3); dy != 10 {
		t.Fatalf("Wrong number of lines: %v", dy)
	}
	w.Multiplier = 0
	if _, dy := w.Lines(20, 3); dy != 6 {
		t.Fatalf("Wrong number of lines: %v", dy)
	}
	w = WheelEvent{DY: -30, Unit: WHEEL_UNIT_PIXELS}
	if _, dy := w.Lines(20, 3); dy != -1.5 {
		t.Fatalf("Wrong number of lines: %v", dy)
	}
	if s := (LEFT_MOUSE_BUTTON | RIGHT_MOUSE_BUTTON).String(); s != "LEFT|RIGHT" {
		t.Fatalf("Wrong string for buttons: %s", s)
	}
}
