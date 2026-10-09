// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import "github.com/kovidgoyal/kitty/tools/tui/loop"

// The edge implementation can register these hooks from its own file's init().
// Settings keys and persistence are shared; all edge operations stay in that
// implementation. A nil registration is an unavailable strategy, never a
// fallback to resizing the whole window.
type strategy_hooks struct {
	OnActivate   func(*handler) error
	OnDeactivate func(*handler) error
	OnKey        func(*handler, *loop.KeyEvent) error
	OnText       func(*handler, string) error
	OnResponse   func(*handler, rc_response) (bool, error)
	Draw         func(*handler)
}

var edge_strategy *strategy_hooks

func (h *handler) active_strategy() string {
	if h.settings.Strategy == "edge" {
		return "edge"
	}
	return "window"
}

func (h *handler) active_hooks() *strategy_hooks {
	if h.active_strategy() == "edge" {
		return edge_strategy
	}
	return nil
}

func (h *handler) active_preferences() strategy_settings {
	return h.settings.preferences(h.active_strategy())
}

// Also used by an edge strategy when turning a key into a move request.
func (h *handler) resize_step(mods loop.KeyModifiers) (multiplier int, fraction float64) {
	mods &= ^(loop.CAPS_LOCK | loop.NUM_LOCK)
	if mods == loop.CTRL {
		return 2, 0
	}
	p := h.active_preferences()
	if (p.Modifier == "alt" && mods == loop.ALT) || (p.Modifier == "shift" && mods == loop.SHIFT) {
		return 1, h.fraction
	}
	return 1, 0
}
