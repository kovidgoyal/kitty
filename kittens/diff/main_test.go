package diff

import (
	"testing"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

func TestDiffLoopSetupAndCapabilities(t *testing.T) {
	prevConf, prevLp := conf, lp
	t.Cleanup(func() {
		conf, lp = prevConf, prevLp
	})
	conf = &Config{}
	var err error
	lp, err = loop.New()
	if err != nil {
		t.Fatal(err)
	}
	h := setup_loop(lp, "left", "right")
	if h == nil {
		t.Fatal("expected non-nil handler")
	}

	if lp.OnCapabilitiesReceived == nil {
		t.Fatal("expected OnCapabilitiesReceived to be set")
	}

	// Verify that OnCapabilitiesReceived forwards capabilities to handler cleanly
	tc := loop.TerminalCapabilities{
		KeyboardProtocol: true,
		ColorPreference:  loop.LIGHT_COLOR_PREFERENCE,
	}
	if err := lp.OnCapabilitiesReceived(tc); err != nil {
		t.Fatalf("unexpected error from OnCapabilitiesReceived: %s", err)
	}
	if !h.terminal_capabilities_received {
		t.Fatal("expected h.terminal_capabilities_received to be true")
	}
}
