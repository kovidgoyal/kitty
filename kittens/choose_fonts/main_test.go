package choose_fonts

import (
	"testing"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

func TestChooseFontsLoopSetup(t *testing.T) {
	lp, err := loop.New()
	if err != nil {
		t.Fatal(err)
	}

	opts := &Options{}
	h := setup_loop(lp, opts)
	if h == nil {
		t.Fatal("expected handler to be non-nil")
	}

	if lp.KittenRequiringKeyboardProtocol() != kittenName {
		t.Fatalf("expected loop to require keyboard protocol for %q, got %q", kittenName, lp.KittenRequiringKeyboardProtocol())
	}
	if lp.OnInitialize == nil {
		t.Fatal("expected OnInitialize to be registered")
	}
	if lp.OnCapabilitiesReceived == nil {
		t.Fatal("expected OnCapabilitiesReceived to be registered")
	}
	if lp.OnFinalize == nil {
		t.Fatal("expected OnFinalize to be registered")
	}
	if lp.OnKeyEvent == nil {
		t.Fatal("expected OnKeyEvent to be registered")
	}
	if lp.OnText == nil {
		t.Fatal("expected OnText to be registered")
	}
	if lp.OnMouseEvent == nil {
		t.Fatal("expected OnMouseEvent to be registered")
	}
}
