// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package config

import (
	"fmt"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print

func TestStringLiteralParsing(t *testing.T) {
	for q, expected := range map[string]string{
		`abc`:                    `abc`,
		`a\nb\M`:                 "a\nb\\M",
		`a\x20\x1\u1234\123\12|`: "a \\x1\u1234\123\x0a|",
	} {
		actual, err := StringLiteral(q)
		if err != nil {
			t.Fatal(err)
		}
		if expected != actual {
			t.Fatalf("Failed with input: %#v\n%#v != %#v", q, expected, actual)
		}
	}
}

func TestParseMap(t *testing.T) {
	// Test without --allow-fallback (default "shifted")
	ka, err := ParseMap("ctrl+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "shifted" {
		t.Fatalf("Expected AllowFallback 'shifted', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}
	if diff := cmp.Diff([]string{"ctrl+c"}, ka.Normalized_keys); diff != "" {
		t.Fatalf("Keys mismatch:\n%s", diff)
	}

	// Test with --allow-fallback=ascii
	ka, err = ParseMap("--allow-fallback=ascii ctrl+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "ascii" {
		t.Fatalf("Expected AllowFallback 'ascii', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}

	// Test with --allow-fallback=shifted,ascii
	ka, err = ParseMap("--allow-fallback=shifted,ascii cmd+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "shifted,ascii" {
		t.Fatalf("Expected AllowFallback 'shifted,ascii', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}
	if diff := cmp.Diff([]string{"super+c"}, ka.Normalized_keys); diff != "" {
		t.Fatalf("Keys mismatch:\n%s", diff)
	}

	// Test with --allow-fallback and action args
	ka, err = ParseMap("--allow-fallback=shifted,ascii ctrl+shift+f launch --type=tab grep")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "shifted,ascii" {
		t.Fatalf("Expected AllowFallback 'shifted,ascii', got %#v", ka.AllowFallback)
	}
	if ka.Name != "launch" {
		t.Fatalf("Expected Name 'launch', got %#v", ka.Name)
	}
	if ka.Args != "--type=tab grep" {
		t.Fatalf("Expected Args '--type=tab grep', got %#v", ka.Args)
	}

	// Test space form: --allow-fallback ascii (without =)
	ka, err = ParseMap("--allow-fallback ascii ctrl+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "ascii" {
		t.Fatalf("Expected AllowFallback 'ascii', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}
	if diff := cmp.Diff([]string{"ctrl+c"}, ka.Normalized_keys); diff != "" {
		t.Fatalf("Keys mismatch:\n%s", diff)
	}

	// Test space form: --allow-fallback shifted,ascii
	ka, err = ParseMap("--allow-fallback shifted,ascii cmd+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "shifted,ascii" {
		t.Fatalf("Expected AllowFallback 'shifted,ascii', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}

	// Test --allow-fallback=none (equals form)
	ka, err = ParseMap("--allow-fallback=none ctrl+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "" {
		t.Fatalf("Expected AllowFallback '', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}

	// Test --allow-fallback none (space form)
	ka, err = ParseMap("--allow-fallback none ctrl+c copy_to_clipboard")
	if err != nil {
		t.Fatal(err)
	}
	if ka.AllowFallback != "" {
		t.Fatalf("Expected AllowFallback '', got %#v", ka.AllowFallback)
	}
	if ka.Name != "copy_to_clipboard" {
		t.Fatalf("Expected Name 'copy_to_clipboard', got %#v", ka.Name)
	}

	// Test error: unknown flag
	_, err = ParseMap("--allow-fallbak=ascii ctrl+c copy")
	if err == nil {
		t.Fatal("Expected error for unknown flag --allow-fallbak")
	}

	// Test error: unknown flag without =
	_, err = ParseMap("--unknown ctrl+c copy")
	if err == nil {
		t.Fatal("Expected error for unknown flag --unknown")
	}

	// Test error: invalid allow-fallback value
	_, err = ParseMap("--allow-fallback=typo ctrl+c copy")
	if err == nil {
		t.Fatal("Expected error for invalid allow-fallback value 'typo'")
	}

	// Test error: invalid allow-fallback value in space form
	_, err = ParseMap("--allow-fallback typo ctrl+c copy")
	if err == nil {
		t.Fatal("Expected error for invalid allow-fallback value 'typo' in space form")
	}
}

func TestNormalizeShortcuts(t *testing.T) {
	for q, expected_ := range map[string]string{
		`a`:           `a`,
		`+`:           `plus`,
		`cmd+b>opt+>`: `super+b alt+>`,
		`cmd+>>opt+>`: `super+> alt+>`,
	} {
		expected := strings.Split(expected_, " ")
		actual := NormalizeShortcuts(q)
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("failed with input: %#v\n%s", q, diff)
		}
	}
}

func TestShortcutTrackerMatchPriority(t *testing.T) {
	// Helper to create a KeyAction with a given spec and AllowFallback.
	makeAction := func(name, spec, allowFallback string) *KeyAction {
		return &KeyAction{Name: name, Normalized_keys: NormalizeShortcuts(spec), AllowFallback: allowFallback}
	}
	// Helper to simulate a key press event.
	makeEv := func(key, shiftedKey, alternateKey string, mods loop.KeyModifiers) *loop.KeyEvent {
		return &loop.KeyEvent{Type: loop.PRESS, Key: key, ShiftedKey: shiftedKey, AlternateKey: alternateKey, Mods: mods}
	}

	// Scenario 1: shifted key event — "shifted,ascii" shortcut wins over "ascii,shifted"
	actions := []*KeyAction{
		makeAction("ascii_shifted", "a", "ascii,shifted"),
		makeAction("shifted_ascii", "a", "shifted,ascii"),
	}
	// Shift+A with ShiftedKey="a": matches via shifted fallback for both
	tracker := ShortcutTracker{}
	ev := makeEv("A", "a", "", loop.SHIFT)
	result := tracker.Match(ev, actions)
	if result == nil || result.Name != "shifted_ascii" {
		name := "<nil>"
		if result != nil {
			name = result.Name
		}
		t.Fatalf("shifted key: expected 'shifted_ascii' (shifted first), got %q", name)
	}

	// Scenario 2: alternate (non-ASCII) key event — "ascii,shifted" shortcut wins over "shifted,ascii"
	actions2 := []*KeyAction{
		makeAction("shifted_ascii", "ctrl+c", "shifted,ascii"),
		makeAction("ascii_shifted", "ctrl+c", "ascii,shifted"),
	}
	// Cyrillic "с" with AlternateKey="c": matches via ascii fallback for both
	tracker2 := ShortcutTracker{}
	ev2 := makeEv("с", "", "c", loop.CTRL)
	result2 := tracker2.Match(ev2, actions2)
	if result2 == nil || result2.Name != "ascii_shifted" {
		name := "<nil>"
		if result2 != nil {
			name = result2.Name
		}
		t.Fatalf("ascii key: expected 'ascii_shifted' (ascii first), got %q", name)
	}

	// Scenario 3: direct match wins over any fallback match
	// Event: Cyrillic "с" with ctrl + AlternateKey="c"; two shortcuts: one direct match for Cyrillic key,
	// one matching via ascii fallback.
	actions3 := []*KeyAction{
		makeAction("fallback", "ctrl+c", "ascii"),
		makeAction("direct", "ctrl+с", ""),
	}
	tracker3 := ShortcutTracker{}
	ev3 := makeEv("с", "", "c", loop.CTRL)
	result3 := tracker3.Match(ev3, actions3)
	if result3 == nil || result3.Name != "direct" {
		name := "<nil>"
		if result3 != nil {
			name = result3.Name
		}
		t.Fatalf("direct match: expected 'direct', got %q", name)
	}

	// Scenario 4: single-type AllowFallback has same priority as first position in two-type AllowFallback
	// "shifted" only vs "shifted,ascii" — when matching via shifted key, both have priority 1, so first in list wins
	actions4 := []*KeyAction{
		makeAction("shifted_only", "a", "shifted"),
		makeAction("shifted_ascii", "a", "shifted,ascii"),
	}
	tracker4 := ShortcutTracker{}
	ev4 := makeEv("A", "a", "", loop.SHIFT)
	result4 := tracker4.Match(ev4, actions4)
	// Both have priority 1 (shifted at position 0); first encountered wins
	if result4 == nil || result4.Name != "shifted_only" {
		name := "<nil>"
		if result4 != nil {
			name = result4.Name
		}
		t.Fatalf("single vs two-type (shifted): expected 'shifted_only', got %q", name)
	}
}
