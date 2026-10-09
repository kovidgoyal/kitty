// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

func TestResizeSettingsPersistence(t *testing.T) {
	path := filepath.Join(t.TempDir(), "kitty", "resize-window.json")
	s, err := load_settings(path)
	if err != nil || !reflect.DeepEqual(s, default_settings()) {
		t.Fatalf("missing settings: %+v, %v", s, err)
	}
	changes := [][3]string{
		{"window", "modifier", "shift"}, {"window", "fraction", "1/7"},
		{"edge", "modifier", "alt"}, {"edge", "fraction", "1/4"}, {"edge", "strategy", "edge"},
	}
	for _, change := range changes {
		if _, err := update_settings(path, change[0], change[1], change[2]); err != nil {
			t.Fatal(err)
		}
	}
	s, err = load_settings(path)
	if err != nil || s.Strategy != "edge" || s.Strategies["window"] != (strategy_settings{"shift", "1/7"}) ||
		s.Strategies["edge"] != (strategy_settings{"alt", "1/4"}) {
		t.Fatalf("profiles did not persist independently: %+v, %v", s, err)
	}
	if _, err := update_settings(path, "window", "strategy", "window"); err != nil {
		t.Fatal(err)
	}
	reopened, err := load_settings(path)
	if err != nil || reopened.Strategy != "window" || !reflect.DeepEqual(reopened.Strategies, s.Strategies) {
		t.Fatalf("switching strategy changed its preferences: %+v, %v", reopened, err)
	}
}

func TestResizeSettingsValidation(t *testing.T) {
	path := filepath.Join(t.TempDir(), "resize-window.json")
	for _, raw := range []string{
		`{`, `{"version":2}`, `{"strategy":"unknown"}`,
		`{"strategies":{"window":{"modifier":"meta"}}}`,
		`{"strategies":{"edge":{"fraction":"0"}}}`,
		`{"strategies":{"window":{"fraction":"NaN"}}}`,
		`{"strategies":{"window":{"fraction":"4/3"}}}`,
	} {
		if err := os.WriteFile(path, []byte(raw), 0o600); err != nil {
			t.Fatal(err)
		}
		if _, err := load_settings(path); err == nil {
			t.Fatalf("accepted invalid settings %s", raw)
		}
		if _, err := update_settings(path, "window", "modifier", "shift"); err == nil {
			t.Fatalf("overwrote invalid settings %s", raw)
		}
		data, err := os.ReadFile(path)
		if err != nil || string(data) != raw {
			t.Fatalf("changed invalid file: %s, %v", data, err)
		}
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	for _, change := range [][3]string{{"window", "modifier", "meta"}, {"edge", "fraction", "-1"}, {"unknown", "strategy", "unknown"}} {
		if _, err := update_settings(path, change[0], change[1], change[2]); err == nil {
			t.Fatalf("accepted invalid update %v", change)
		}
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("invalid update created a settings file")
	}
}

func TestResizeSettingsDefaultsAndOverrides(t *testing.T) {
	path := filepath.Join(t.TempDir(), "resize-window.json")
	raw := `{"strategy":"edge","strategies":{"window":{"fraction":"1/4"},"edge":{"fraction":"1/5"}}}`
	if err := os.WriteFile(path, []byte(raw), 0o600); err != nil {
		t.Fatal(err)
	}
	opts := &Options{Fraction: "1/3", Strategy: "window"}
	s, err := settings_for_invocation(path, opts, nil)
	if err != nil || s.Strategy != "edge" || s.preferences("edge") != (strategy_settings{"alt", "1/5"}) ||
		s.preferences("window") != (strategy_settings{"alt", "1/4"}) {
		t.Fatalf("defaults masked saved preferences: %+v, %v", s, err)
	}
	s, err = settings_for_invocation(path, opts, map[string]bool{"Fraction": true, "Strategy": true})
	if err != nil || s.Strategy != "window" || s.preferences("window").Fraction != "1/3" || s.preferences("edge").Fraction != "1/5" {
		t.Fatalf("explicit options did not override only the active profile: %+v, %v", s, err)
	}
	data, err := os.ReadFile(path)
	if err != nil || string(data) != raw {
		t.Fatal("command-line overrides changed the saved settings")
	}
}

func TestResizeSettingsMerge(t *testing.T) {
	path := filepath.Join(t.TempDir(), "resize-window.json")
	// Two pages opened with the same initial values, then edit different fields.
	first, _ := load_settings(path)
	second, _ := load_settings(path)
	if !reflect.DeepEqual(first, second) {
		t.Fatal("different starting state")
	}
	if _, err := update_settings(path, first.Strategy, "fraction", "1/2"); err != nil {
		t.Fatal(err)
	}
	if _, err := update_settings(path, second.Strategy, "modifier", "shift"); err != nil {
		t.Fatal(err)
	}
	s, err := load_settings(path)
	if err != nil || s.preferences("window") != (strategy_settings{"shift", "1/2"}) {
		t.Fatalf("a stale page overwrote another page's change: %+v, %v", s, err)
	}
}

func TestResizeSettingsModifiers(t *testing.T) {
	for _, strategy := range []string{"window", "edge"} {
		for _, modifier := range []string{"alt", "shift"} {
			s := default_settings()
			s.Strategy = strategy
			s.Strategies[strategy] = strategy_settings{Modifier: modifier, Fraction: "1/7"}
			h := &handler{opts: &Options{}, settings: s}
			if err := h.sync_preferences(); err != nil {
				t.Fatal(err)
			}
			for _, mods := range []loop.KeyModifiers{0, loop.SHIFT, loop.ALT, loop.CTRL, loop.CTRL | loop.SHIFT} {
				multiplier, fraction := h.resize_step(mods | loop.CAPS_LOCK)
				wantMultiplier, wantFraction := 1, 0.0
				if mods == loop.CTRL {
					wantMultiplier = 2
				} else if (modifier == "alt" && mods == loop.ALT) || (modifier == "shift" && mods == loop.SHIFT) {
					wantFraction = 1.0 / 7
				}
				if multiplier != wantMultiplier || fraction != wantFraction {
					t.Fatalf("%s %s mods=%v: got %d/%v", strategy, modifier, mods, multiplier, fraction)
				}
			}
		}
	}
}

func TestResizeStrategyHooks(t *testing.T) {
	old := edge_strategy
	t.Cleanup(func() { edge_strategy = old })
	if edge_strategy == nil || edge_strategy.OnKey == nil || edge_strategy.OnText == nil || edge_strategy.Draw == nil {
		t.Fatal("Edge strategy is missing its interaction handlers")
	}
	s := default_settings()
	s.Strategy = "edge"
	// No loop: accidentally routing Window keys to a resize would panic.
	h := &handler{settings: s, opts: &Options{}, edge_ready: true}
	for _, text := range []string{"w", "W", "n", "t", "s"} {
		if err := h.on_text(text); err != nil {
			t.Fatal(err)
		}
	}
	e := &loop.KeyEvent{Key: "w", Type: loop.PRESS}
	if err := h.on_key(e); err != nil || e.Handled {
		t.Fatalf("Edge handled a Window resize key: %v", err)
	}
	keys, texts := 0, 0
	edge_strategy = &strategy_hooks{
		OnKey:  func(h *handler, e *loop.KeyEvent) error { keys++; e.Handled = true; return nil },
		OnText: func(h *handler, text string) error { texts++; return nil },
	}
	if err := h.on_key(e); err != nil || !e.Handled || keys != 1 {
		t.Fatalf("registered key hook not used: %v", err)
	}
	if err := h.on_text("h"); err != nil || texts != 1 {
		t.Fatalf("registered text hook not used: %v", err)
	}
}

func TestResizeStrategySwitchKeepsCommandLineOverride(t *testing.T) {
	path := filepath.Join(t.TempDir(), "resize-window.json")
	opts := &Options{Fraction: "1/4", Strategy: "window"}
	s, err := settings_for_invocation(path, opts, map[string]bool{"Fraction": true, "Strategy": true})
	if err != nil {
		t.Fatal(err)
	}
	h := &handler{opts: opts, settings: s, settings_path: path}
	if err := h.sync_preferences(); err != nil {
		t.Fatal(err)
	}
	for _, strategy := range []string{"edge", "window"} {
		saved, err := update_settings(path, strategy, "strategy", strategy)
		if err != nil {
			t.Fatal(err)
		}
		if err := h.apply_saved_setting(strategy, "strategy", saved); err != nil || h.active_strategy() != strategy {
			t.Fatalf("did not switch to %s: %v", strategy, err)
		}
	}
	if h.active_preferences().Fraction != "1/4" || h.fraction != 0.25 {
		t.Fatalf("switching strategy discarded the --fraction override: %+v", h.active_preferences())
	}
	saved, err := load_settings(path)
	if err != nil || saved.preferences("window").Fraction != "1/3" {
		t.Fatalf("the --fraction override was saved: %+v, %v", saved, err)
	}
}
