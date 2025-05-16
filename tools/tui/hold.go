// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"errors"
	"fmt"
	"os"
	"os/exec"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print

func HoldTillEnter(start_with_newline bool) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return
	}
	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		if start_with_newline {
			lp.QueueWriteString("\r\n")
		}
		lp.QueueWriteString("\x1b[1;32mPress Enter or Esc to exit\x1b[m")
		return "", nil
	}
	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		return ""
	}

	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("enter") || event.MatchesPressOrRepeat("kp_enter") || event.MatchesPressOrRepeat("esc") || event.MatchesPressOrRepeat("ctrl+c") || event.MatchesPressOrRepeat("ctrl+d") {
			event.Handled = true
			lp.Quit(0)
		}
		return nil
	}
	lp.Run()
}

func ExecAndHoldTillEnter(cmdline []string) {
	if len(cmdline) == 0 {
		HoldTillEnter(false)
		os.Exit(0)
	}
	var cmd *exec.Cmd
	if len(cmdline) == 1 {
		cmd = exec.Command(cmdline[0])
	} else {
		cmd = exec.Command(cmdline[0], cmdline[1:]...)
	}
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	var ee *exec.ExitError
	err := cmd.Run()
	is_exit_error := err != nil && errors.As(err, &ee)
	if err != nil && !is_exit_error {
		fmt.Fprintln(os.Stderr, err)
	}
	HoldTillEnter(true)
	if err == nil {
		os.Exit(0)
	}
	if is_exit_error {
		os.Exit(ee.ExitCode())
	}
	os.Exit(1)
}
