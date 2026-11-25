package themes

import (
	"testing"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

func TestThemesLoopSetup(t *testing.T) {
	lp, err := loop.New()
	if err != nil {
		t.Fatal(err)
	}

	opts := &Options{}
	cached := &CachedData{Category: "All"}
	h := setup_loop(lp, opts, cached)
	if h == nil {
		t.Fatal("expected handler to be non-nil")
	}

	if lp.KittenRequiringKeyboardProtocol() != kittenName {
		t.Fatalf("expected loop to require keyboard protocol for %q, got %q", kittenName, lp.KittenRequiringKeyboardProtocol())
	}
	if lp.OnInitialize == nil {
		t.Fatal("expected OnInitialize to be registered")
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
}
