package resize_window

import (
	"testing"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

func TestResizeWindowLoopSetup(t *testing.T) {
	lp, err := loop.New(loop.FullKeyboardProtocol)
	if err != nil {
		t.Fatal(err)
	}
	opts := &Options{Fraction: "0.5"}
	seen := make(map[string]bool)
	h, err := setup_loop(lp, opts, seen)
	if err != nil {
		t.Fatal(err)
	}
	if h == nil {
		t.Fatal("expected handler to be non-nil")
	}
	if lp.KittenRequiringKeyboardProtocol() != kittenName {
		t.Fatalf("expected loop to require keyboard protocol for %q, got %q", kittenName, lp.KittenRequiringKeyboardProtocol())
	}
	if lp.OnInitialize == nil {
		t.Fatal("expected OnInitialize to be registered")
	}
	if lp.OnResize == nil {
		t.Fatal("expected OnResize to be registered")
	}
	if lp.OnText == nil {
		t.Fatal("expected OnText to be registered")
	}
	if lp.OnKeyEvent == nil {
		t.Fatal("expected OnKeyEvent to be registered")
	}
	if lp.OnRCResponse == nil {
		t.Fatal("expected OnRCResponse to be registered")
	}
}
