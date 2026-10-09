// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
	"golang.org/x/sys/unix"
)

type strategy_settings struct {
	Modifier string `json:"modifier"`
	Fraction string `json:"fraction"`
}

type resize_settings struct {
	Version    int                          `json:"version"`
	Strategy   string                       `json:"strategy"`
	Strategies map[string]strategy_settings `json:"strategies"`
}

func default_settings() resize_settings {
	return resize_settings{Version: 1, Strategy: "window", Strategies: map[string]strategy_settings{
		"window": {Modifier: "alt", Fraction: "1/3"},
		"edge":   {Modifier: "shift", Fraction: "1/3"},
	}}
}

func (s *resize_settings) preferences(strategy string) strategy_settings {
	if p, ok := s.Strategies[strategy]; ok {
		return p
	}
	return default_settings().Strategies[strategy]
}

func (s *resize_settings) normalize() error {
	defaults := default_settings()
	if s.Version == 0 {
		s.Version = 1
	}
	if s.Version != 1 {
		return fmt.Errorf("unsupported resize settings version: %d", s.Version)
	}
	if s.Strategy == "" {
		s.Strategy = defaults.Strategy
	}
	if s.Strategy != "window" && s.Strategy != "edge" {
		return fmt.Errorf("unknown resize strategy: %q", s.Strategy)
	}
	if s.Strategies == nil {
		s.Strategies = make(map[string]strategy_settings)
	}
	for name, fallback := range defaults.Strategies {
		p := s.Strategies[name]
		if p.Modifier == "" {
			p.Modifier = fallback.Modifier
		}
		if p.Modifier != "alt" && p.Modifier != "shift" {
			return fmt.Errorf("invalid %s modifier: %q", name, p.Modifier)
		}
		p.Fraction = strings.TrimSpace(p.Fraction)
		if p.Fraction == "" {
			p.Fraction = fallback.Fraction
		}
		if _, err := parse_fraction(p.Fraction); err != nil {
			return fmt.Errorf("invalid %s fraction: %w", name, err)
		}
		s.Strategies[name] = p
	}
	return nil
}

func load_settings(path string) (resize_settings, error) {
	s := default_settings()
	raw, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return s, nil
	}
	if err != nil {
		return s, err
	}
	if err := json.Unmarshal(raw, &s); err != nil {
		return default_settings(), err
	}
	if err := s.normalize(); err != nil {
		return default_settings(), err
	}
	return s, nil
}

// Merge one changed field with the latest saved settings. Separate resize
// windows must not overwrite each other's strategy preferences.
func update_settings(path, strategy, field, value string) (resize_settings, error) {
	if strategy != "window" && strategy != "edge" {
		return resize_settings{}, fmt.Errorf("unknown resize strategy: %q", strategy)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return resize_settings{}, err
	}
	lock, err := os.OpenFile(path+".lock", os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return resize_settings{}, err
	}
	defer lock.Close()
	if err := unix.Flock(int(lock.Fd()), unix.LOCK_EX); err != nil {
		return resize_settings{}, err
	}
	defer unix.Flock(int(lock.Fd()), unix.LOCK_UN)
	s, err := load_settings(path)
	if err != nil {
		return s, err
	}
	p := s.preferences(strategy)
	switch field {
	case "strategy":
		s.Strategy = strategy
	case "modifier":
		p.Modifier = value
	case "fraction":
		p.Fraction = value
	default:
		return s, fmt.Errorf("unknown resize setting: %q", field)
	}
	s.Strategies[strategy] = p
	if err := s.normalize(); err != nil {
		return s, err
	}
	raw, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return s, err
	}
	raw = append(raw, '\n')
	return s, utils.AtomicWriteFile(path, bytes.NewReader(raw), 0o600)
}
