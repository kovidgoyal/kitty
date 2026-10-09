// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"fmt"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var fraction_presets = []string{"1/2", "1/3", "1/4", "1/5", "1/10", "1"}

func (h *handler) clear_saved_status() bool {
	if h.status != "Saved" {
		return false
	}
	h.status = ""
	if h.saved_timer != 0 {
		h.lp.RemoveTimer(h.saved_timer)
		h.saved_timer = 0
	}
	return true
}

func (h *handler) show_saved_status() error {
	if h.saved_timer != 0 {
		h.lp.RemoveTimer(h.saved_timer)
	}
	h.status = "Saved"
	id, err := h.lp.AddTimer(2*time.Second, false, func(id loop.IdType) error {
		if h.saved_timer == id {
			h.saved_timer = 0
			if h.status == "Saved" {
				h.status = ""
				h.draw_screen()
			}
		}
		return nil
	})
	h.saved_timer = id
	return err
}

func (h *handler) sync_preferences() error {
	p := h.active_preferences()
	fraction, err := parse_fraction(p.Fraction)
	if err == nil {
		h.fraction = fraction
		h.opts.Fraction = p.Fraction
		h.opts.Strategy = h.active_strategy()
	}
	return err
}

func (h *handler) change_setting(field, value string) error {
	strategy := h.active_strategy()
	if field == "strategy" {
		strategy = value
	}
	saved, err := update_settings(h.settings_path, strategy, field, value)
	if err != nil {
		h.status = "Could not save: " + err.Error()
		h.draw_screen()
		return nil
	}
	// A command-line override remains active for this invocation until the user
	// changes that field. Save operations merge against disk, not stale UI state.
	if field == "strategy" {
		if hooks := h.active_hooks(); hooks != nil && hooks.OnDeactivate != nil {
			if err := hooks.OnDeactivate(h); err != nil {
				return err
			}
		}
		h.settings.Strategy = saved.Strategy
		h.settings.Strategies[strategy] = saved.preferences(strategy)
	} else {
		p := h.active_preferences()
		if field == "modifier" {
			p.Modifier = saved.preferences(strategy).Modifier
		} else {
			p.Fraction = saved.preferences(strategy).Fraction
		}
		h.settings.Strategies[strategy] = p
	}
	if err := h.sync_preferences(); err != nil {
		return err
	}
	h.page = ""
	if err := h.show_saved_status(); err != nil {
		return err
	}
	if field == "strategy" {
		if hooks := h.active_hooks(); hooks != nil && hooks.OnActivate != nil {
			if err := hooks.OnActivate(h); err != nil {
				return err
			}
		}
	}
	h.draw_screen()
	return nil
}

func (h *handler) on_text(text string) error {
	if h.clear_saved_status() {
		h.draw_screen()
	}
	if h.page == "edit-fraction" {
		if len(h.fraction_input)+len(text) <= 32 && strings.Trim(text, "0123456789./eE+- ") == "" {
			h.fraction_input += text
			h.status = ""
			h.draw_screen()
		}
		return nil
	}
	key := strings.ToLower(text)
	if h.page == "fraction" {
		if len(key) == 1 && key[0] >= '1' && int(key[0]-'1') < len(fraction_presets) {
			return h.change_setting("fraction", fraction_presets[key[0]-'1'])
		}
		if key == "c" {
			h.page, h.fraction_input, h.status = "edit-fraction", "", ""
			h.draw_screen()
		}
		return nil
	}
	switch key {
	case "1":
		return h.change_setting("strategy", "window")
	case "2":
		return h.change_setting("strategy", "edge")
	case "m":
		modifier := "shift"
		if h.active_preferences().Modifier == "shift" {
			modifier = "alt"
		}
		return h.change_setting("modifier", modifier)
	case "f":
		if hooks := h.active_hooks(); hooks != nil && hooks.OnSettings != nil {
			hooks.OnSettings(h)
		}
		h.page, h.status = "fraction", ""
		h.draw_screen()
		return nil
	}
	if h.active_strategy() == "edge" {
		if hooks := h.active_hooks(); hooks != nil && hooks.OnText != nil {
			return hooks.OnText(h, text)
		}
		return nil
	}
	return h.window_on_text(text)
}

func (h *handler) on_key(e *loop.KeyEvent) error {
	if e.Type == loop.RELEASE {
		e.Handled = true
		return nil
	}
	if h.clear_saved_status() {
		h.draw_screen()
	}
	if h.page != "" {
		if e.MatchesPressOrRepeat("esc") {
			e.Handled = true
			h.page, h.status = "", ""
			h.draw_screen()
			return nil
		}
		if h.page == "edit-fraction" {
			if e.MatchesPressOrRepeat("enter") {
				e.Handled = true
				value := strings.TrimSpace(h.fraction_input)
				if _, err := parse_fraction(value); err != nil {
					h.status = "Use a fraction greater than 0 and at most 1"
					h.draw_screen()
					return nil
				}
				return h.change_setting("fraction", value)
			}
			if e.MatchesPressOrRepeat("backspace") || e.MatchesPressOrRepeat("ctrl+u") {
				e.Handled = true
				if e.MatchesPressOrRepeat("ctrl+u") {
					h.fraction_input = ""
				} else if len(h.fraction_input) > 0 {
					h.fraction_input = h.fraction_input[:len(h.fraction_input)-1]
				}
				h.status = ""
				h.draw_screen()
				return nil
			}
		}
		if e.Mods & ^(loop.SHIFT|loop.CAPS_LOCK|loop.NUM_LOCK) == 0 && len(e.Key) == 1 {
			e.Handled = true
			if e.Text != "" {
				return h.on_text(e.Text)
			}
			return h.on_text(e.Key)
		}
		return nil
	}
	for _, key := range []string{"1", "2", "m", "f"} {
		if e.MatchesPressOrRepeat(key) {
			e.Handled = true
			if e.Type == loop.PRESS {
				return h.on_text(key)
			}
			return nil
		}
	}
	if h.active_strategy() == "edge" {
		if hooks := h.active_hooks(); hooks != nil && hooks.OnKey != nil {
			if err := hooks.OnKey(h, e); err != nil || e.Handled {
				return err
			}
		}
	} else if err := h.window_on_key(e); err != nil || e.Handled {
		return err
	}
	if e.MatchesPressOrRepeat("esc") || e.MatchesPressOrRepeat("q") {
		e.Handled = true
		h.lp.Quit(0)
	}
	return nil
}

func (h *handler) draw_settings_page() {
	lp, ctx := h.lp, h.ctx
	lp.Println(lp.SprintStyled("bold fg=white", "Choose a fraction"))
	lp.Println("For the " + h.active_strategy() + " strategy")
	lp.Println()
	if h.page == "edit-fraction" {
		lp.Println("Enter a ratio or decimal, e.g. 1/7 or 0.2")
		lp.Println("Fraction: " + ctx.Magenta(h.fraction_input) + "_")
		lp.Println("Enter: save    Esc: cancel    Ctrl+U: clear")
	} else {
		for i, fraction := range fraction_presets {
			lp.Println(fmt.Sprintf("%d: %s", i+1, ctx.Green(fraction)))
		}
		lp.Println("C: custom fraction    Esc: cancel")
		lp.Println("Current: " + ctx.Magenta(h.active_preferences().Fraction))
	}
	if h.status != "" {
		lp.Println(h.status)
	}
}
