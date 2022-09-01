// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"errors"
	"fmt"
	"strings"

	"kitty/tools/tui/loop"
	"kitty/tools/wcswidth"
)

type KilledBySignal struct {
	Msg        string
	SignalName string
}

func (self *KilledBySignal) Error() string { return self.Msg }

var Canceled = errors.New("Canceled by user")

func ReadPassword(prompt string, kill_if_signaled bool) (password string, err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	shadow := ""
	if err != nil {
		return
	}

	lp.OnInitialize = func() (string, error) {
		lp.QueueWriteString(prompt)
		return "\r\n", nil
	}

	lp.OnText = func(text string, from_key_event bool, in_bracketed_paste bool) error {
		old_width := wcswidth.Stringwidth(password)
		password += text
		new_width := wcswidth.Stringwidth(password)
		if new_width > old_width {
			extra := strings.Repeat("*", new_width-old_width)
			lp.QueueWriteString(extra)
			shadow += extra
		}
		return nil
	}

	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
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
					lp.QueueWriteString(strings.Repeat("\x08\x1b[P", delta))
				}
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
		lp.QueueWriteString("\r" + prompt + shadow)
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
