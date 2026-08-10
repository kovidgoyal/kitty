// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package resize_window

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print

type handler struct {
	lp            *loop.Loop
	opts          *Options
	ctx           *markup.Context
	original_size loop.ScreenSize
	print_on_fail string
}

type rc_response struct {
	Ok    bool            `json:"ok"`
	Error string          `json:"error"`
	Tb    string          `json:"tb"`
	Data  json.RawMessage `json:"data"`
}

func (h *handler) do_window_resize(is_decrease, is_horizontal, reset bool, multiplier int) error {
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
	ec, err := resize_command_escape_code(increment, axis)
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
	if json_is_truthy(response.Data) {
		h.lp.Beep()
	}
	return nil
}

func (h *handler) on_text(text string) error {
	text = strings.ToUpper(text)
	switch text {
	case "W", "N", "T", "S", "R":
		return h.do_window_resize(text == "N" || text == "S", text == "W" || text == "N", text == "R", 1)
	case "Q":
		h.lp.Quit(0)
	}
	return nil
}

func (h *handler) on_key(e *loop.KeyEvent) error {
	if e.MatchesPressOrRepeat("esc") {
		e.Handled = true
		h.lp.Quit(0)
		return nil
	}
	for _, k := range []string{"w", "n", "t", "s"} {
		if e.MatchesPressOrRepeat("ctrl+" + k) {
			e.Handled = true
			return h.do_window_resize(k == "n" || k == "s", k == "w" || k == "n", false, 2)
		}
	}
	return nil
}

func (h *handler) draw_screen() {
	lp, ctx := h.lp, h.ctx
	lp.StartAtomicUpdate()
	defer lp.EndAtomicUpdate()
	lp.ClearScreen()
	lp.Println(lp.SprintStyled("bold fg=white", "Resize this window"))
	lp.Println()
	lp.Println("Press one of the following keys:")
	lp.Println("  " + ctx.Green("W") + "ider")
	lp.Println("  " + ctx.Green("N") + "arrower")
	lp.Println("  " + ctx.Green("T") + "aller")
	lp.Println("  " + ctx.Green("S") + "horter")
	lp.Println("  " + ctx.Red("R") + "eset")
	lp.Println()
	lp.Println("Press " + lp.SprintStyled("italic", "Esc") + " to quit resize mode")
	lp.Println("Hold down " + lp.SprintStyled("italic", "Ctrl") + " to double step size")
	lp.Println()
	lp.Println(lp.SprintStyled("bold fg=white", "Sizes"))
	lp.Printf("Original: %d rows %d cols\r\n", h.original_size.HeightCells, h.original_size.WidthCells)
	if sz, err := lp.ScreenSize(); err == nil {
		lp.Printf("Current:  %s rows %s cols\r\n",
			ctx.Magenta(fmt.Sprint(sz.HeightCells)), ctx.Magenta(fmt.Sprint(sz.WidthCells)))
	}
}

func run_loop(opts *Options) (rc int, err error) {
	lp, err := loop.New(loop.FullKeyboardProtocol)
	if err != nil {
		return 1, err
	}
	h := &handler{lp: lp, opts: opts, ctx: markup.New(true)}
	lp.OnInitialize = func() (string, error) {
		sz, err := lp.ScreenSize()
		if err != nil {
			return "", err
		}
		h.original_size = sz
		lp.SetCursorVisible(false)
		lp.AllowLineWrapping(false)
		h.draw_screen()
		return "", nil
	}
	lp.OnResize = func(old, new loop.ScreenSize) error { h.draw_screen(); return nil }
	lp.OnText = func(text string, from_key_event, in_bracketed_paste bool) error { return h.on_text(text) }
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
	return run_loop(opts)
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
