package loop

import (
	"testing"
	"time"
)

func TestZeroScreenSize(t *testing.T) {
	lp := Loop{}
	if err := lp.handle_csi([]byte("48;0;0;0;0t")); err != nil {
		t.Fatal(err)
	}
	if err := lp.handle_csi([]byte("48;24;0;480;0t")); err != nil {
		t.Fatal(err)
	}
	s := lp.screen_size
	if s.WidthCells != 0 || s.CellWidth != 0 || s.HeightCells != 24 || s.CellHeight != 20 {
		t.Fatalf("unexpected screen size: %#v", s)
	}
}

func TestMalformedResizeReport(t *testing.T) {
	lp := Loop{}
	for _, csi := range []string{"t", "1t", "48t", "48;t", "8;24;80;0;0t", "48;-1;80;0;0t", "48;a;b;c;dt"} {
		if err := lp.handle_csi([]byte(csi)); err != nil {
			t.Fatalf("unexpected error for %#v: %s", csi, err)
		}
		if lp.seen_inband_resize {
			t.Fatalf("malformed resize report %#v was accepted", csi)
		}
	}
	if err := lp.handle_csi([]byte("48;24;80;480;800;1t")); err != nil {
		t.Fatal(err)
	}
	s := lp.screen_size
	if s.HeightCells != 24 || s.WidthCells != 80 || s.HeightPx != 480 || s.WidthPx != 800 {
		t.Fatalf("unexpected screen size: %#v", s)
	}
}

func TestKeyboardProtocolRequirementResponses(t *testing.T) {
	expectedErr := keyboardProtocolErrorMessage("mykitten")

	// Test rejection when Device Attributes (?c) is received without keyboard protocol acknowledgment
	lp := Loop{}
	lp.timers = make([]*timer, 0, 8)
	lp.RequireKittyKeyboardProtocol("mykitten")
	if lp.keyboard_protocol_watchdog_timer == 0 {
		t.Fatal("expected watchdog timer to be set")
	}
	err := lp.handle_csi([]byte("?61;1;2c"))
	if err == nil {
		t.Fatal("expected error when keyboard protocol is not acknowledged before ?c, got nil")
	}
	if err.Error() != expectedErr {
		t.Fatalf("expected error %q, got %q", expectedErr, err.Error())
	}

	// Test acceptance and chaining when keyboard protocol is acknowledged (?u) followed by ?c
	lp2 := Loop{}
	lp2.timers = make([]*timer, 0, 8)
	lp2.RequireKittyKeyboardProtocol("mykitten")
	if lp2.keyboard_protocol_watchdog_timer == 0 {
		t.Fatal("expected watchdog timer to be set")
	}
	capabilitiesReceived := false
	lp2.OnCapabilitiesReceived = func(tc TerminalCapabilities) error {
		capabilitiesReceived = true
		if !tc.KeyboardProtocol {
			t.Fatal("expected KeyboardProtocol to be true in OnCapabilitiesReceived")
		}
		return nil
	}
	if err := lp2.handle_csi([]byte("?1u")); err != nil {
		t.Fatalf("unexpected error on ?u: %s", err)
	}
	if lp2.keyboard_protocol_watchdog_timer != 0 {
		t.Fatalf("expected watchdog timer to be cancelled after ?u, got %d", lp2.keyboard_protocol_watchdog_timer)
	}
	if err := lp2.handle_csi([]byte("?61;1;2c")); err != nil {
		t.Fatalf("unexpected error on ?c after ?u: %s", err)
	}
	if !capabilitiesReceived {
		t.Fatal("expected OnCapabilitiesReceived to be called")
	}
}

func TestKeyboardProtocolWatchdog(t *testing.T) {
	expectedErr := keyboardProtocolErrorMessage("test_timeout")

	// 1. Watchdog fires after 2 seconds if protocol response is not received
	lp := Loop{}
	lp.timers = make([]*timer, 0, 8)
	lp.RequireKittyKeyboardProtocol("test_timeout")
	if lp.keyboard_protocol_watchdog_timer == 0 {
		t.Fatal("expected watchdog timer to be set")
	}
	if len(lp.timers) != 1 {
		t.Fatalf("expected 1 timer registered, got %d", len(lp.timers))
	}

	// Before 2 seconds deadline: no error
	if err := lp.dispatch_timers(time.Now().Add(500 * time.Millisecond)); err != nil {
		t.Fatalf("unexpected error before deadline: %s", err)
	}

	// After 2 seconds deadline: triggers timeout error
	err := lp.dispatch_timers(time.Now().Add(3 * time.Second))
	if err == nil {
		t.Fatal("expected watchdog timeout error, got nil")
	}
	if err.Error() != expectedErr {
		t.Fatalf("expected error %q, got %q", expectedErr, err.Error())
	}

	// 2. Watchdog is cancelled when keyboard protocol is acknowledged
	lp2 := Loop{}
	lp2.timers = make([]*timer, 0, 8)
	lp2.RequireKittyKeyboardProtocol("test_timeout")
	if lp2.keyboard_protocol_watchdog_timer == 0 {
		t.Fatal("expected watchdog timer to be set")
	}
	if err := lp2.handle_csi([]byte("?1u")); err != nil {
		t.Fatalf("unexpected error on ?u: %s", err)
	}
	if lp2.keyboard_protocol_watchdog_timer != 0 {
		t.Fatalf("expected watchdog timer to be reset to 0 after ?u, got %d", lp2.keyboard_protocol_watchdog_timer)
	}
	if len(lp2.timers) != 0 {
		t.Fatalf("expected timer to be removed after ?u, got %d", len(lp2.timers))
	}
	// After 3 seconds: no error since timer was cancelled
	if err := lp2.dispatch_timers(time.Now().Add(3 * time.Second)); err != nil {
		t.Fatalf("unexpected error on dispatch after timer cancelled: %s", err)
	}
}
