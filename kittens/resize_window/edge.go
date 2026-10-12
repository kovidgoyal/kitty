// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

type edge_state struct {
	Edges    []string `json:"edges"`
	Selected string   `json:"selected"`
	Divider  string   `json:"divider"`
	Status   string   `json:"status"`
	Failed   bool     `json:"failed"`
}

type edge_input struct {
	key        string
	multiplier int
	fraction   float64
}

var edge_keys = []struct{ key, edge, arrow string }{
	{"h", "left", "left"}, {"j", "bottom", "down"},
	{"k", "top", "up"}, {"l", "right", "right"},
}

func init() {
	edge_strategy = &strategy_hooks{
		OnActivate: func(h *handler) error {
			h.edge_queue = nil
			return h.send_edge_command("start", "none", 0, 0)
		},
		OnDeactivate: func(h *handler) error { h.edge_queue = nil; return nil },
		OnSettings:   func(h *handler) { h.edge_queue = nil },
		OnKey:        func(h *handler, e *loop.KeyEvent) error { return h.on_edge_key(e) },
		OnText: func(h *handler, text string) error {
			mods := loop.KeyModifiers(0)
			if text != strings.ToLower(text) {
				mods = loop.SHIFT
			}
			multiplier, fraction := h.resize_step(mods)
			return h.edge_action(edge_input{strings.ToLower(text), multiplier, fraction})
		},
		OnResponse: func(h *handler, response rc_response) (bool, error) {
			var data string
			if json.Unmarshal(response.Data, &data) != nil {
				return false, nil
			}
			var fields map[string]json.RawMessage
			if json.Unmarshal([]byte(data), &fields) != nil {
				return false, nil
			}
			if _, found := fields["edges"]; !found {
				return false, nil
			}
			return true, h.on_edge_response(response.Data)
		},
		Draw: func(h *handler) { h.draw_edge_screen() },
	}
}

func (h *handler) send_edge_command(operation, edge string, increment int, fraction float64) error {
	ec, err := edge_command_escape_code(operation, edge, h.edge_state.Divider, increment, fraction)
	if err != nil {
		return err
	}
	h.edge_pending = true
	h.lp.QueueWriteString(ec)
	return nil
}

func (h *handler) edge_action(input edge_input) error {
	if input.key == "q" || input.key == "enter" {
		h.edge_queue = nil
		h.lp.Quit(0)
		return nil
	}
	if h.edge_pending || !h.edge_ready {
		h.edge_queue = append(h.edge_queue, input)
		return nil
	}
	switch input.key {
	case "esc":
		if h.edge_state.Selected == "" {
			h.lp.Quit(0)
			return nil
		}
		return h.send_edge_command("state", "none", 0, 0)
	case "r":
		return h.send_edge_command("reset", "none", 0, 0)
	}
	for _, k := range edge_keys {
		if input.key != k.key {
			continue
		}
		if h.edge_state.Selected == "" {
			return h.send_edge_command("select", k.edge, 0, 0)
		}
		horizontal := h.edge_state.Selected == "left" || h.edge_state.Selected == "right"
		if horizontal != (k.edge == "left" || k.edge == "right") {
			h.edge_state.Status = "Use J/K to move this edge"
			if horizontal {
				h.edge_state.Status = "Use H/L to move this edge"
			}
			h.draw_screen()
			return nil
		}
		increment := h.opts.HorizontalIncrement
		if !horizontal {
			increment = h.opts.VerticalIncrement
		}
		increment *= input.multiplier
		if k.edge == "left" || k.edge == "top" {
			increment = -increment
		}
		return h.send_edge_command("move", h.edge_state.Selected, increment, input.fraction)
	}
	return nil
}

func (h *handler) on_edge_key(e *loop.KeyEvent) error {
	for _, k := range edge_keys {
		for _, key := range []string{k.key, k.arrow} {
			for _, modifier := range []string{"alt+", "ctrl+", "", "shift+"} {
				if e.MatchesPressOrRepeat(modifier + key) {
					e.Handled = true
					multiplier, fraction := h.resize_step(e.Mods)
					input := edge_input{key: k.key, multiplier: multiplier, fraction: fraction}
					return h.edge_action(input)
				}
			}
		}
	}
	for _, key := range []string{"esc", "enter", "r", "q"} {
		if e.MatchesPressOrRepeat(key) || e.MatchesPressOrRepeat("shift+"+key) {
			e.Handled = true
			return h.edge_action(edge_input{key: key, multiplier: 1})
		}
	}
	if e.Mods.WithoutLocks() & ^loop.SHIFT != 0 && !e.MatchesPressOrRepeat("ctrl+c") && !e.MatchesPressOrRepeat("ctrl+z") {
		e.Handled = true
	}
	return nil
}

func (h *handler) on_edge_response(raw json.RawMessage) error {
	var data string
	if err := json.Unmarshal(raw, &data); err != nil {
		return err
	}
	var state edge_state
	if err := json.Unmarshal([]byte(data), &state); err != nil {
		return err
	}
	h.edge_state = state
	h.edge_pending, h.edge_ready = false, true
	if state.Status != "" {
		// Newer than any local message, which would otherwise hide it
		h.status = ""
	}
	if state.Failed {
		h.lp.Beep()
	}
	h.draw_screen()
	if h.active_strategy() != "edge" || h.page != "" {
		h.edge_queue = nil
		return nil
	}
	for len(h.edge_queue) > 0 && !h.edge_pending && h.active_strategy() == "edge" && h.page == "" {
		input := h.edge_queue[0]
		h.edge_queue = h.edge_queue[1:]
		if err := h.edge_action(input); err != nil {
			return err
		}
	}
	return nil
}

func (h *handler) draw_edge_screen() {
	lp := h.lp
	lp.StartAtomicUpdate()
	defer lp.EndAtomicUpdate()
	lp.ClearScreen()
	title := "Choose an edge"
	if h.edge_state.Selected != "" {
		title = "Move the " + h.edge_state.Selected + " edge"
	}
	lines := []string{lp.SprintStyled("bold fg=white", title)}
	sz, err := lp.ScreenSize()
	if err != nil {
		return
	}
	p := h.active_preferences()
	modifier := "Alt"
	if p.Modifier == "shift" {
		modifier = "Shift"
	}
	lines = append(lines, "Strategy: 1: Window  "+h.ctx.Green("2: Edge"), h.ctx.Green("M")+": "+modifier+"    "+h.ctx.Green("F")+": "+p.Fraction+" (change settings)")
	label := func(edge, text string) string {
		style := "fg=bright-black"
		for _, available := range h.edge_state.Edges {
			if edge == available {
				style = "fg=green"
			}
		}
		if edge == h.edge_state.Selected {
			style = "bold fg=yellow"
		}
		return lp.SprintStyled(style, text)
	}
	if sz.HeightCells >= 16 {
		lines = append(lines,
			"          "+label("top", "K / ↑"),
			"        "+label("top", "┌────────┐"),
			label("left", "H / ←")+"   "+label("left", "│")+"  pane  "+label("right", "│")+"   "+label("right", "L / →"),
			"        "+label("bottom", "└────────┘"),
			"          "+label("bottom", "J / ↓"))
	}
	if h.edge_state.Selected == "" {
		lines = append(lines, "H J K L / arrows: choose an internal edge", "Gray = outside edge    Esc / Q: finish")
		if h.edge_ready && len(h.edge_state.Edges) == 0 {
			lines = append(lines, "No internal edges in this layout")
		}
	} else {
		keys := "J / K / ↓ / ↑"
		if h.edge_state.Selected == "left" || h.edge_state.Selected == "right" {
			keys = "H / L / ← / →"
		}
		lines = append(lines, h.ctx.Green(keys)+": move the selected divider", "Esc: choose edge    Enter / Q: finish")
	}
	lines = append(lines, modifier+": "+p.Fraction+" remaining steps    Ctrl: 2x", "R: restore original sizes")
	if sz.HeightCells >= 18 {
		lines = append(lines, fmt.Sprintf("Original: %d rows %d cols", h.original_size.HeightCells, h.original_size.WidthCells))
	}
	lines = append(lines, fmt.Sprintf("Current:  %s rows %s cols", h.ctx.Magenta(fmt.Sprint(sz.HeightCells)), h.ctx.Magenta(fmt.Sprint(sz.WidthCells))))
	limit := max(1, int(sz.HeightCells)-1)
	status := h.edge_state.Status
	if h.status != "" {
		status = h.status
	}
	if status != "" {
		lines = append(lines[:min(len(lines), max(1, limit-1))], status)
	}
	lp.QueueWriteString(strings.Join(lines[:min(len(lines), limit)], "\r\n"))
}
