// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"errors"
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

type KilledBySignal struct {
	Msg        string
	SignalName string
}

func (self *KilledBySignal) Error() string { return self.Msg }

var Canceled = errors.New("Canceled by user")

const password_symbol = "🔒"

func ReadPassword(prompt string, kill_if_signaled bool) (password string, err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.FullKeyboardProtocol)
	shadow := ""
	if err != nil {
		return
	}
	capspress_was_locked := false
	has_caps_lock := false

	redraw_prompt := func() {
		lp.QueueWriteString("\r")
		lp.ClearToEndOfLine()
		if has_caps_lock {
			lp.QueueWriteString("\x1b[31m[CapsLock on!]\x1b[39m ")
		}
		lp.QueueWriteString(prompt + shadow + password_symbol)
	}

	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		lp.QueueWriteString(prompt + password_symbol)
		return "", nil
	}

	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		lp.SetCursorShape(loop.BLOCK_CURSOR, true)
		return "\r\n"
	}

	lp.OnText = func(text string, from_key_event bool, in_bracketed_paste bool) error {
		old_width := wcswidth.Stringwidth(password)
		password += text
		new_width := wcswidth.Stringwidth(password)
		if new_width > old_width {
			shadow += strings.Repeat("*", new_width-old_width)
		}
		redraw_prompt()
		return nil
	}

	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		has_caps := false
		if strings.ToLower(event.Key) == "caps_lock" {
			if event.Type == loop.RELEASE {
				has_caps = !capspress_was_locked
				capspress_was_locked = false
			} else {
				capspress_was_locked = event.HasCapsLock()
				has_caps = true
			}
		} else {
			has_caps = event.HasCapsLock()
		}
		if has_caps_lock != has_caps {
			has_caps_lock = has_caps
			redraw_prompt()
		}
		if event.MatchesPressOrRepeat("backspace") || event.MatchesPressOrRepeat("delete") {
			event.Handled = true
			if len(password) > 0 {
				old_width := wcswidth.Stringwidth(password)
				password = password[:len(password)-1]
				new_width := wcswidth.Stringwidth(password)
				delta := old_width - new_width
				if delta > 0 {
					if delta > len(shadow) {
						delta = len(shadow)
					}
					shadow = shadow[:len(shadow)-delta]
				}
				redraw_prompt()
			} else {
				lp.Beep()
			}
		}
		if event.MatchesPressOrRepeat("enter") || event.MatchesPressOrRepeat("return") {
			event.Handled = true
			if password == "" {
				lp.Quit(1)
			} else {
				lp.Quit(0)
			}
		}
		if event.MatchesPressOrRepeat("esc") {
			event.Handled = true
			lp.Quit(1)
			return Canceled
		}
		return nil
	}

	lp.OnResumeFromStop = func() error {
		redraw_prompt()
		return nil
	}

	err = lp.Run()
	if err != nil {
		return
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		if kill_if_signaled {
			lp.KillIfSignalled()
			return
		}
		return "", &KilledBySignal{Msg: fmt.Sprint("Killed by signal: ", ds), SignalName: ds}
	}
	if lp.ExitCode() != 0 {
		password = ""
	}
	return password, nil
}
