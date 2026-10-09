// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type handler struct {
	lp             *loop.Loop
	opts           *Options
	ctx            *markup.Context
	original_size  loop.ScreenSize
	print_on_fail  string
	fraction       float64
	settings       resize_settings
	settings_path  string
	page           string
	fraction_input string
	status         string
	saved_timer    loop.IdType
	edge_state     edge_state
	edge_pending   bool
	edge_ready     bool
	edge_queue     []edge_input
}

func parse_fraction(value string) (float64, error) {
	parts := strings.Split(value, "/")
	if len(parts) > 2 {
		return 0, fmt.Errorf("invalid fraction: %q", value)
	}
	n, err := strconv.ParseFloat(strings.TrimSpace(parts[0]), 64)
	if err == nil && len(parts) == 2 {
		var d float64
		d, err = strconv.ParseFloat(strings.TrimSpace(parts[1]), 64)
		if err == nil {
			if d <= 0 || math.IsNaN(d) || math.IsInf(d, 0) {
				err = fmt.Errorf("invalid denominator")
			} else {
				n /= d
			}
		}
	}
	if err != nil || math.IsNaN(n) || math.IsInf(n, 0) || n <= 0 || n > 1 {
		return 0, fmt.Errorf("--fraction must be greater than zero and at most one, got %q", value)
	}
	return n, nil
}

type rc_response struct {
	Ok    bool            `json:"ok"`
	Error string          `json:"error"`
	Tb    string          `json:"tb"`
	Data  json.RawMessage `json:"data"`
}

func (h *handler) do_window_resize(is_decrease, is_horizontal, reset bool, multiplier int, fraction float64) error {
	increment := h.opts.HorizontalIncrement
	if !is_horizontal {
		increment = h.opts.VerticalIncrement
	}
	increment *= multiplier
	if is_decrease {
		increment = -increment
	}
	axis := "reset"
	if !reset {
		if is_horizontal {
			axis = "horizontal"
		} else {
			axis = "vertical"
		}
	}
	ec, err := resize_command_escape_code(increment, axis, fraction)
	if err != nil {
		return err
	}
	h.lp.QueueWriteString(ec)
	return nil
}

// json_is_truthy mirrors Python's truthiness test (`if value:`) for a decoded
// JSON value, so on_rc_response's "beep if data is truthy" check matches the
// behavior of kittens/resize_window/main.py's on_kitty_cmd_response. The
// resize-window RC command returns bool | None | str for "data" (see
// kitty/rc/resize_window.py), so False/None/"" must all be treated as falsy.
func json_is_truthy(raw json.RawMessage) bool {
	if len(raw) == 0 {
		return false
	}
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		return false
	}
	switch val := v.(type) {
	case nil:
		return false
	case bool:
		return val
	case float64:
		return val != 0
	case string:
		return val != ""
	case []any:
		return len(val) != 0
	case map[string]any:
		return len(val) != 0
	default:
		return true
	}
}

func (h *handler) on_rc_response(raw []byte) error {
	var response rc_response
	if err := json.Unmarshal(raw, &response); err != nil {
		return err
	}
	if !response.Ok {
		emsg := response.Error
		if response.Tb != "" {
			emsg += "\n" + response.Tb
		}
		h.print_on_fail = emsg
		h.lp.Quit(1)
		return nil
	}
	if edge_strategy != nil && edge_strategy.OnResponse != nil {
		if handled, err := edge_strategy.OnResponse(h, response); err != nil || handled {
			return err
		}
	}
	if json_is_truthy(response.Data) {
		h.lp.Beep()
	}
	return nil
}

func (h *handler) window_on_text(text string) error {
	modifier := loop.KeyModifiers(0)
	if text != strings.ToLower(text) {
		modifier = loop.SHIFT
	}
	text = strings.ToUpper(text)
	switch text {
	case "W", "N", "T", "S", "R":
		multiplier, fraction := h.resize_step(modifier)
		if text == "R" {
			multiplier, fraction = 1, 0
		}
		return h.do_window_resize(text == "N" || text == "S", text == "W" || text == "N", text == "R", multiplier, fraction)
	case "Q":
		h.lp.Quit(0)
	}
	return nil
}

func (h *handler) window_on_key(e *loop.KeyEvent) error {
	for _, k := range []string{"w", "n", "t", "s"} {
		if e.MatchesPressOrRepeat(k) || e.MatchesPressOrRepeat("shift+"+k) || e.MatchesPressOrRepeat("alt+"+k) || e.MatchesPressOrRepeat("ctrl+"+k) {
			e.Handled = true
			multiplier, fraction := h.resize_step(e.Mods)
			return h.do_window_resize(k == "n" || k == "s", k == "w" || k == "n", false, multiplier, fraction)
		}
	}
	for _, k := range []string{"r", "q"} {
		if e.MatchesPressOrRepeat(k) || e.MatchesPressOrRepeat("shift+"+k) {
			e.Handled = true
			return h.window_on_text(k)
		}
	}
	return nil
}

func (h *handler) draw_screen() {
	if h.page == "" && h.active_strategy() == "edge" && edge_strategy != nil {
		h.draw_edge_screen()
		return
	}
	lp, ctx := h.lp, h.ctx
	lp.StartAtomicUpdate()
	defer lp.EndAtomicUpdate()
	lp.ClearScreen()
	if h.page != "" {
		h.draw_settings_page()
		return
	}
	title := "Resize this window"
	if h.active_strategy() == "edge" {
		title = "Resize an edge"
	}
	lp.Println(lp.SprintStyled("bold fg=white", title))
	window, edge := "1: Window", "2: Edge"
	if h.active_strategy() == "window" {
		window = ctx.Green(window)
	} else {
		edge = ctx.Green(edge)
	}
	lp.Println("Strategy: " + window + "  " + edge)
	p := h.active_preferences()
	modifier := "Alt"
	if p.Modifier == "shift" {
		modifier = "Shift"
	}
	lp.Println(ctx.Green("M") + ": " + modifier + "    " + ctx.Green("F") + ": " + p.Fraction + " (change settings)")
	lp.Println()
	if h.active_strategy() == "window" {
		lp.Println("  " + ctx.Green("W") + "ider")
		lp.Println("  " + ctx.Green("N") + "arrower")
		lp.Println("  " + ctx.Green("T") + "aller")
		lp.Println("  " + ctx.Green("S") + "horter")
		lp.Println("  " + ctx.Red("R") + "eset")
	} else if hooks := h.active_hooks(); hooks != nil && hooks.Draw != nil {
		hooks.Draw(h)
	} else {
		lp.Println("Edge strategy is not available yet.")
		lp.Println("Its modifier and fraction can still be saved.")
	}
	lp.Println(lp.SprintStyled("italic", "Esc") + ": quit    " + lp.SprintStyled("italic", "Ctrl") + ": double step size")
	lp.Println(lp.SprintStyled("italic", modifier) + ": " + p.Fraction + " of the remaining steps")
	status := "Settings saved automatically"
	if h.status != "" {
		status = h.status
	}
	lp.Println(status)
	lp.Println(lp.SprintStyled("bold fg=white", "Sizes"))
	lp.Printf("Original: %d rows %d cols\r\n", h.original_size.HeightCells, h.original_size.WidthCells)
	if sz, err := lp.ScreenSize(); err == nil {
		lp.Printf("Current:  %s rows %s cols\r\n",
			ctx.Magenta(fmt.Sprint(sz.HeightCells)), ctx.Magenta(fmt.Sprint(sz.WidthCells)))
	}
}

func run_loop(opts *Options, seen map[string]bool) (rc int, err error) {
	_, err = parse_fraction(opts.Fraction)
	if err != nil {
		return 1, err
	}
	lp, err := loop.New(loop.FullKeyboardProtocol)
	if err != nil {
		return 1, err
	}
	path := filepath.Join(utils.ConfigDir(), "resize-window.json")
	settings, load_err := settings_for_invocation(path, opts, seen)
	h := &handler{lp: lp, opts: opts, settings: settings, settings_path: path, ctx: markup.New(true)}
	if load_err != nil {
		h.status = "Could not load settings: " + load_err.Error()
	}
	if err := h.sync_preferences(); err != nil {
		return 1, err
	}
	lp.OnInitialize = func() (string, error) {
		sz, err := lp.ScreenSize()
		if err != nil {
			return "", err
		}
		h.original_size = sz
		lp.SetCursorVisible(false)
		lp.AllowLineWrapping(false)
		h.draw_screen()
		if hooks := h.active_hooks(); hooks != nil && hooks.OnActivate != nil {
			if err := hooks.OnActivate(h); err != nil {
				return "", err
			}
		}
		return "", nil
	}
	lp.OnResize = func(old, new loop.ScreenSize) error { h.draw_screen(); return nil }
	lp.OnText = func(text string, from_key_event, in_bracketed_paste bool) error {
		if in_bracketed_paste && h.page != "edit-fraction" {
			return nil
		}
		return h.on_text(text)
	}
	lp.OnKeyEvent = h.on_key
	lp.OnRCResponse = h.on_rc_response
	err = lp.Run()
	if err != nil {
		return 1, err
	}
	lp.KillIfSignalled()
	if h.print_on_fail != "" {
		fmt.Fprintln(os.Stderr, h.print_on_fail)
		tui.HoldTillEnter(false)
	}
	return lp.ExitCode(), nil
}

func main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	return run_loop(opts, cmd.OptionsSeenOnCommandLine())
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
