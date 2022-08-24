package tui

import (
	"errors"
	"fmt"
	"strings"

	"kitty/tools/wcswidth"
)

type KilledBySignal struct {
	Msg        string
	SignalName string
}

func (self *KilledBySignal) Error() string { return self.Msg }

var Canceled = errors.New("Canceled by user")

func ReadPassword(prompt string, kill_if_signaled bool) (password string, err error) {
	loop, err := CreateLoop()
	shadow := ""
	if err != nil {
		return
	}

	loop.OnInitialize = func(loop *Loop) string { return "\r\n" }

	loop.OnText = func(loop *Loop, text string, from_key_event bool, in_bracketed_paste bool) error {
		old_width := wcswidth.Stringwidth(password)
		password += text
		new_width := wcswidth.Stringwidth(password)
		if new_width > old_width {
			extra := strings.Repeat("*", new_width-old_width)
			loop.QueueWriteString(extra)
			shadow += extra
		}
		return nil
	}

	loop.OnKeyEvent = func(loop *Loop, event *KeyEvent) error {
		if event.MatchesPressOrRepeat("backscape") || event.MatchesPressOrRepeat("delete") {
			event.Handled = true
			if len(password) > 0 {
				old_width := wcswidth.Stringwidth(password)
				password = password[:len(password)-1]
				new_width := wcswidth.Stringwidth(password)
				delta := new_width - old_width
				if delta > 0 {
					if delta > len(shadow) {
						delta = len(shadow)
					}
					shadow = shadow[:len(shadow)-delta]
					loop.QueueWriteString(strings.Repeat("\x08\x1b[P", delta))
				}
			} else {
				loop.Beep()
			}
		}
		if event.MatchesPressOrRepeat("enter") || event.MatchesPressOrRepeat("return") {
			event.Handled = true
			if password == "" {
				loop.Quit(1)
			} else {
				loop.Quit(0)
			}
		}
		if event.MatchesPressOrRepeat("esc") {
			event.Handled = true
			loop.Quit(1)
			return Canceled
		}
		return nil
	}

	err = loop.Run()
	if err != nil {
		return
	}
	ds := loop.DeathSignalName()
	if ds != "" {
		if kill_if_signaled {
			loop.KillIfSignalled()
			return
		}
		return "", &KilledBySignal{Msg: fmt.Sprint("Killed by signal: ", ds), SignalName: ds}
	}
	if loop.ExitCode() != 0 {
		password = ""
	}
	return password, nil
}
