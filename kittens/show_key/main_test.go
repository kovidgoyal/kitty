package show_key

import (
	"testing"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

func TestShowKeyLoopSetup(t *testing.T) {
	lp, err := loop.New(loop.FullKeyboardProtocol)
	if err != nil {
		t.Fatal(err)
	}

	setup_kitty_loop(lp)

	if lp.KittenRequiringKeyboardProtocol() != kittenName {
		t.Fatalf("expected loop to require keyboard protocol for %q, got %q", kittenName, lp.KittenRequiringKeyboardProtocol())
	}
	if lp.OnInitialize == nil {
		t.Fatal("expected OnInitialize to be registered")
	}
	if lp.OnKeyEvent == nil {
		t.Fatal("expected OnKeyEvent to be registered")
	}
	if lp.OnText == nil {
		t.Fatal("expected OnText to be registered")
	}
}

func TestShowKeyKeyModeRouting(t *testing.T) {
	origRunner := runner
	t.Cleanup(func() {
		runner = origRunner
	})

	var kittyCalled, legacyCalled bool
	runner.kitty = func(opts *Options) error {
		kittyCalled = true
		return nil
	}
	runner.legacy = func(opts *Options) error {
		legacyCalled = true
		return nil
	}

	// 1. Default kitty mode invokes run_kitty_loop
	kittyCalled, legacyCalled = false, false
	rc, err := main(nil, &Options{KeyMode: "kitty"}, nil)
	if rc != 0 || err != nil {
		t.Fatalf("unexpected return from main: rc=%d, err=%v", rc, err)
	}
	if !kittyCalled {
		t.Fatal("expected runner.kitty to be invoked for KeyMode=kitty")
	}
	if legacyCalled {
		t.Fatal("runner.legacy should not be invoked for KeyMode=kitty")
	}

	// 2. Legacy modes bypass kitty loop and invoke run_legacy_loop
	for _, mode := range []string{"normal", "application", "unchanged"} {
		kittyCalled, legacyCalled = false, false
		rc, err := main(nil, &Options{KeyMode: mode}, nil)
		if rc != 0 || err != nil {
			t.Fatalf("unexpected return from main for mode %s: rc=%d, err=%v", mode, rc, err)
		}
		if kittyCalled {
			t.Fatalf("runner.kitty should not be invoked for mode %s", mode)
		}
		if !legacyCalled {
			t.Fatalf("expected runner.legacy to be invoked for mode %s", mode)
		}
	}
}
