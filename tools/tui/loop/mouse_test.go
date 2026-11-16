// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestDecodeWheelEvent(t *testing.T) {
	sz := ScreenSize{WidthPx: 1000, HeightPx: 500, CellWidth: 10, CellHeight: 20}
	ev := func(x, y int, mods KeyModifiers, w WheelEvent) *MouseEvent {
		ans := &MouseEvent{Event_type: MOUSE_WHEEL, Mods: mods, Wheel: w}
		ans.Pixel.X, ans.Pixel.Y = x, y
		ans.Cell.X, ans.Cell.Y = x/10, y/20
		return ans
	}
	for csi, expected := range map[string]*MouseEvent{
		">45;65;0;120;1:5;1;0;0;1M": ev(45, 65, 0, WheelEvent{DY: 120, Unit: WHEEL_UNIT_V120, Multiplier: 5, Source: WHEEL_SOURCE_WHEEL}),
		">45;65;-3;-42;2:1.5;2;2;0;5M": ev(45, 65, CTRL, WheelEvent{
			DX: -3, DY: -42, Unit: WHEEL_UNIT_PIXELS, Multiplier: 1.5, Source: WHEEL_SOURCE_FINGER, Phase: WHEEL_PHASE_CHANGED}),
		">45;65;0;0;2;2;3;3;1M": ev(45, 65, 0, WheelEvent{
			Unit: WHEEL_UNIT_PIXELS, Source: WHEEL_SOURCE_FINGER, Phase: WHEEL_PHASE_ENDED, Momentum: true, Inverted: true}),
		// Unknown parameters and sub-parameters are ignored
		">45;65:7;0;120:3;1:5:9;1;0;0;1;99:1M": ev(45, 65, 0, WheelEvent{DY: 120, Unit: WHEEL_UNIT_V120, Multiplier: 5, Source: WHEEL_SOURCE_WHEEL}),
		// Too few parameters or wrong final byte
		">45;65;0;120;1;1;0;0M":     nil,
		">45;65;0;120;1;1;0;0;1m":   nil,
		">45;65;x;120;1;1;0;0;1M":   nil,
		"<64;45;65M":                {Buttons: MOUSE_WHEEL_UP, Pixel: struct{ X, Y int }{45, 65}, Cell: struct{ X, Y int }{4, 3}},
		">45;65;0;120;1:0;1;0;0;1M": ev(45, 65, 0, WheelEvent{DY: 120, Unit: WHEEL_UNIT_V120, Source: WHEEL_SOURCE_WHEEL}),
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
}
