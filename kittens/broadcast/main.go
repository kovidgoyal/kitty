// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package broadcast

import (
	"encoding/base64"
	"os"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

type handler struct {
	lp              *loop.Loop
	opts            *Options
	ctx             *markup.Context
	payload         broadcast_payload
	initial_strings []string
	hide_input      bool
	session_started bool
	line_edit       line_edit
}

func b64text(text string) string {
	return "base64:" + base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(text))
}

func (h *handler) broadcast_data(data string) error {
	p := h.payload
	p.Data = data
	ec, err := send_text_escape_code(p)
	if err != nil {
		return err
	}
	h.lp.QueueWriteString(ec)
	return nil
}

func (h *handler) broadcast_text(text string) error { return h.broadcast_data(b64text(text)) }

func (h *handler) commit_line() {
	h.lp.RestoreCursorPosition()
	h.lp.SaveCursorPosition()
	h.lp.ClearToEndOfScreen()
	h.line_edit.write(h.lp)
}

func (h *handler) end_line() {
	h.lp.Println()
	h.line_edit.clear()
	h.lp.SaveCursorPosition()
}

func (h *handler) initialize() (string, error) {
	h.session_started = true
	ec, err := session_escape_code(h.payload, true)
	if err != nil {
		return "", err
	}
	h.lp.QueueWriteString(ec)
	h.lp.Println("Type the text to broadcast below, press", h.ctx.Yellow(h.opts.EndSession), "to quit:")
	for _, x := range h.initial_strings {
		if err := h.broadcast_text(x); err != nil {
			return "", err
		}
	}
	h.lp.SaveCursorPosition()
	return "", nil
}

func (h *handler) on_text(text string) error {
	if err := h.broadcast_text(text); err != nil {
		return err
	}
	if !h.hide_input {
		h.line_edit.on_text(text)
	}
	h.commit_line()
	return nil
}

func (h *handler) on_key(e *loop.KeyEvent) error {
	if e.MatchesPressOrRepeat(strings.ToLower(h.opts.HideInputToggle)) {
		e.Handled = true
		h.hide_input = !h.hide_input
		h.lp.SetCursorVisible(!h.hide_input)
		if h.hide_input {
			h.end_line()
			h.lp.Println("Input hidden, press", h.ctx.Yellow(h.opts.HideInputToggle), "to unhide:")
			h.end_line()
		}
		return nil
	}
	if e.MatchesPressOrRepeat(strings.ToLower(h.opts.EndSession)) {
		e.Handled = true
		h.lp.Quit(0)
		return nil
	}
	if e.MatchesPressOrRepeat("ctrl+c") {
		e.Handled = true
		if err := h.broadcast_text("\x03"); err != nil {
			return err
		}
		h.line_edit.clear()
		h.commit_line()
		return nil
	}
	if e.MatchesPressOrRepeat("ctrl+d") {
		e.Handled = true
		return h.broadcast_text("\x04")
	}
	if !h.hide_input && h.line_edit.on_key(e) {
		h.commit_line()
	}
	if e.MatchesPressOrRepeat("enter") {
		e.Handled = true
		if err := h.broadcast_text("\r"); err != nil {
			return err
		}
		h.end_line()
		return nil
	}
	if e.Text == "" { // non-text key: forward in kitty-key encoding
		e.Handled = true
		return h.broadcast_data("kitty-key:" + base64.StdEncoding.EncodeToString([]byte(e.AsCSI())))
	}
	return nil
}

func run_loop(opts *Options, args []string) (rc int, err error) {
	lp, err := loop.New(loop.FullKeyboardProtocol, loop.NoAlternateScreen)
	if err != nil {
		return 1, err
	}
	h := &handler{lp: lp, opts: opts, ctx: markup.New(true), initial_strings: args}
	h.payload = broadcast_payload{
		ExcludeActive: true, Match: opts.Match, MatchTab: opts.MatchTab, SessionId: new_session_id(),
	}
	if opts.Match == "" && opts.MatchTab == "" {
		h.payload.All = true
	}
	lp.OnInitialize = h.initialize
	lp.OnResize = func(old, new loop.ScreenSize) error { h.commit_line(); return nil }
	lp.OnText = func(text string, from_key_event, in_bracketed_paste bool) error { return h.on_text(text) }
	lp.OnKeyEvent = h.on_key
	err = lp.Run()
	if h.session_started {
		if ec, err2 := session_escape_code(h.payload, false); err2 == nil {
			os.Stdout.WriteString(ec)
		}
	}
	if err != nil {
		return 1, err
	}
	lp.KillIfSignalled()
	return lp.ExitCode(), nil
}

func main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	return run_loop(opts, args)
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
