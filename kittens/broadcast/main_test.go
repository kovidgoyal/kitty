package broadcast

import (
	"testing"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

func TestBroadcastLoopSetupAndDeferredSession(t *testing.T) {
	lp, err := loop.New(loop.FullKeyboardProtocol, loop.NoAlternateScreen)
	if err != nil {
		t.Fatal(err)
	}

	opts := &Options{
		EndSession:      "ctrl+w",
		HideInputToggle: "ctrl+h",
	}
	initialArgs := []string{"initial text"}

	h := setup_loop(lp, opts, initialArgs)
	if h == nil {
		t.Fatal("expected non-nil handler")
	}

	// 1. Verify loop helper requirement is registered
	if lp.KittenRequiringKeyboardProtocol() != kittenName {
		t.Fatalf("expected kitten %q, got %q", kittenName, lp.KittenRequiringKeyboardProtocol())
	}

	// 2. Before capabilities are received: session must NOT be started
	if h.session_started {
		t.Fatal("expected session_started to be false before capabilities are received")
	}

	// 3. When capabilities are acknowledged, session begins
	tc := loop.TerminalCapabilities{KeyboardProtocol: true}
	if err := lp.OnCapabilitiesReceived(tc); err != nil {
		t.Fatalf("unexpected error from OnCapabilitiesReceived: %s", err)
	}
	if !h.session_started {
		t.Fatal("expected session_started to be true after capabilities are received")
	}
}
