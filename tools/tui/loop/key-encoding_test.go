// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestKeyEventFromCSI(t *testing.T) {

	test_text := func(csi string, expected, alternate string) {
		ev := KeyEventFromCSI(csi)
		if ev == nil {
			t.Fatalf("Failed to get parse %#v", csi)
		}
		if diff := cmp.Diff(expected, ev.Text); diff != "" {
			t.Fatalf("Failed to get text from %#v:\n%s", csi, diff)
		}
		if diff := cmp.Diff(alternate, ev.AlternateKey); diff != "" {
			t.Fatalf("Failed to get alternate from %#v:\n%s", csi, diff)
		}
	}
	test_text("121;;121u", "y", "")
	test_text("121::122;;121u", "y", "z")
}

func TestIsNonASCIIKey(t *testing.T) {
	if !isNonASCIIKey("с") { // Cyrillic с (U+0441)
		t.Fatal("Cyrillic с should be non-ASCII")
	}
	if isNonASCIIKey("c") { // Latin c
		t.Fatal("Latin c should be ASCII")
	}
	if isNonASCIIKey("") {
		t.Fatal("empty string should not be non-ASCII")
	}
	// boundary: U+0080 (first non-ASCII) should be true
	if !isNonASCIIKey("\u0080") {
		t.Fatal("U+0080 should be non-ASCII")
	}
	// boundary: U+007F (DEL, last ASCII) should be false
	if isNonASCIIKey("\u007f") {
		t.Fatal("U+007F should be ASCII")
	}
	// boundary: U+D7FF (last valid BMP char before surrogates) should be true
	if !isNonASCIIKey("\uD7FF") {
		t.Fatal("U+D7FF should be non-ASCII (before PUA)")
	}
	// boundary: U+E000 (first PUA, functional key range) should be false
	if isNonASCIIKey("\uE000") {
		t.Fatal("U+E000 should be excluded (functional key range)")
	}
}

func TestMatchesParsedShortcutWithFallback(t *testing.T) {
	ps := ParseShortcut("ctrl+c")

	// Per-mapping ascii match: Cyrillic key + AlternateKey=c + allow_fallback contains ascii
	ev := &KeyEvent{Type: PRESS, Mods: CTRL, Key: "с", AlternateKey: "c"}
	if !ev.MatchesParsedShortcutWithFallback(ps, PRESS, "shifted,ascii") {
		t.Fatal("should match via AlternateKey with allow_fallback=shifted,ascii")
	}
	if !ev.MatchesParsedShortcutWithFallback(ps, PRESS, "ascii") {
		t.Fatal("should match via AlternateKey with allow_fallback=ascii")
	}

	// Per-mapping no ascii match when allow_fallback=shifted only
	if ev.MatchesParsedShortcutWithFallback(ps, PRESS, "shifted") {
		t.Fatal("should NOT match via AlternateKey with allow_fallback=shifted (no ascii)")
	}

	// No fallback at all
	if ev.MatchesParsedShortcutWithFallback(ps, PRESS, "") {
		t.Fatal("should NOT match with empty allow_fallback")
	}

	// Direct Key match takes priority (always works regardless of allow_fallback)
	evDirect := &KeyEvent{Type: PRESS, Mods: CTRL, Key: "c"}
	if !evDirect.MatchesParsedShortcutWithFallback(ps, PRESS, "") {
		t.Fatal("direct Key match should work even with empty allow_fallback")
	}
	if !evDirect.MatchesParsedShortcutWithFallback(ps, PRESS, "shifted") {
		t.Fatal("direct Key match should work with any allow_fallback")
	}

	// No AlternateKey match when Key is ASCII (Dvorak safety: non-ASCII guard)
	evDvorak := &KeyEvent{Type: PRESS, Mods: CTRL, Key: "x", AlternateKey: "c"}
	if evDvorak.MatchesParsedShortcutWithFallback(ps, PRESS, "ascii") {
		t.Fatal("should NOT match via AlternateKey when Key is ASCII (Dvorak)")
	}

	// Shifted fallback respects per-mapping allow_fallback
	psA := ParseShortcut("a")
	evShifted := &KeyEvent{Type: PRESS, Mods: SHIFT, Key: "A", ShiftedKey: "a"}
	if !evShifted.MatchesParsedShortcutWithFallback(psA, PRESS, "shifted") {
		t.Fatal("shifted fallback should work with allow_fallback=shifted")
	}
	if evShifted.MatchesParsedShortcutWithFallback(psA, PRESS, "ascii") {
		t.Fatal("shifted fallback should NOT work with allow_fallback=ascii only")
	}
	if evShifted.MatchesParsedShortcutWithFallback(psA, PRESS, "") {
		t.Fatal("shifted fallback should NOT work with empty allow_fallback")
	}
}

func TestMatchesParsedShortcutPriorityWithFallback(t *testing.T) {
	psA := ParseShortcut("a")
	psCtrlC := ParseShortcut("ctrl+c")

	// Direct match: priority 0
	evDirect := &KeyEvent{Type: PRESS, Key: "a"}
	if p := evDirect.MatchesParsedShortcutPriorityWithFallback(psA, PRESS, ""); p != 0 {
		t.Fatalf("direct match should have priority 0, got %d", p)
	}

	// No match: priority -1
	evNoMatch := &KeyEvent{Type: PRESS, Key: "b"}
	if p := evNoMatch.MatchesParsedShortcutPriorityWithFallback(psA, PRESS, "shifted,ascii"); p != -1 {
		t.Fatalf("no match should have priority -1, got %d", p)
	}

	// Shifted fallback at position 0 in "shifted,ascii": priority 1
	evShifted := &KeyEvent{Type: PRESS, Mods: SHIFT, Key: "A", ShiftedKey: "a"}
	if p := evShifted.MatchesParsedShortcutPriorityWithFallback(psA, PRESS, "shifted,ascii"); p != 1 {
		t.Fatalf("shifted fallback first in 'shifted,ascii' should have priority 1, got %d", p)
	}

	// Shifted fallback at position 1 in "ascii,shifted": priority 2
	if p := evShifted.MatchesParsedShortcutPriorityWithFallback(psA, PRESS, "ascii,shifted"); p != 2 {
		t.Fatalf("shifted fallback second in 'ascii,shifted' should have priority 2, got %d", p)
	}

	// Shifted fallback only in "shifted": priority 1 (same as first position)
	if p := evShifted.MatchesParsedShortcutPriorityWithFallback(psA, PRESS, "shifted"); p != 1 {
		t.Fatalf("shifted fallback only in 'shifted' should have priority 1, got %d", p)
	}

	// Shifted fallback not allowed: priority -1
	if p := evShifted.MatchesParsedShortcutPriorityWithFallback(psA, PRESS, "ascii"); p != -1 {
		t.Fatalf("shifted fallback not in 'ascii' should have priority -1, got %d", p)
	}

	// ASCII (alternate key) fallback at position 1 in "shifted,ascii": priority 2
	evASCII := &KeyEvent{Type: PRESS, Mods: CTRL, Key: "с", AlternateKey: "c"}
	if p := evASCII.MatchesParsedShortcutPriorityWithFallback(psCtrlC, PRESS, "shifted,ascii"); p != 2 {
		t.Fatalf("ascii fallback second in 'shifted,ascii' should have priority 2, got %d", p)
	}

	// ASCII fallback at position 0 in "ascii,shifted": priority 1
	if p := evASCII.MatchesParsedShortcutPriorityWithFallback(psCtrlC, PRESS, "ascii,shifted"); p != 1 {
		t.Fatalf("ascii fallback first in 'ascii,shifted' should have priority 1, got %d", p)
	}

	// ASCII fallback only in "ascii": priority 1
	if p := evASCII.MatchesParsedShortcutPriorityWithFallback(psCtrlC, PRESS, "ascii"); p != 1 {
		t.Fatalf("ascii fallback only in 'ascii' should have priority 1, got %d", p)
	}
}

func TestMatchesParsedShortcutUnconditionalAlternateKey(t *testing.T) {
	// Unconditional match via MatchesPressOrRepeat (hardcoded shortcuts)
	ev := &KeyEvent{Type: PRESS, Mods: CTRL, Key: "с", AlternateKey: "c"}
	if !ev.MatchesPressOrRepeat("ctrl+c") {
		t.Fatal("MatchesPressOrRepeat should match via AlternateKey with non-ASCII guard")
	}

	// Direct Key match takes priority in unconditional mode too
	evDirect := &KeyEvent{Type: PRESS, Mods: CTRL, Key: "c"}
	if !evDirect.MatchesPressOrRepeat("ctrl+c") {
		t.Fatal("direct Key match should work in unconditional mode")
	}

	// No AlternateKey match when Key is ASCII (Dvorak safety)
	evDvorak := &KeyEvent{Type: PRESS, Mods: CTRL, Key: "x", AlternateKey: "c"}
	if evDvorak.MatchesPressOrRepeat("ctrl+c") {
		t.Fatal("should NOT match via AlternateKey when Key is ASCII in unconditional mode")
	}

	// ShiftedKey still works unconditionally
	evShifted := &KeyEvent{Type: PRESS, Mods: SHIFT, Key: "A", ShiftedKey: "a"}
	if !evShifted.MatchesPressOrRepeat("a") {
		t.Fatal("ShiftedKey should match unconditionally in MatchesParsedShortcut")
	}
}
