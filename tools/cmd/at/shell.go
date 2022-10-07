// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"errors"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/google/shlex"

	"kitty/tools/cli"
	"kitty/tools/cli/markup"
	"kitty/tools/tui/loop"
	"kitty/tools/tui/readline"
)

var _ = fmt.Print

var formatter *markup.Context

const prompt = "🐱 "

var ErrExec = errors.New("Execute command")

func shell_loop(rl *readline.Readline, kill_if_signaled bool) (int, error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return 1, err
	}
	rl.ChangeLoopAndResetText(lp)

	lp.OnInitialize = func() (string, error) {
		rl.Start()
		return "", nil
	}
	lp.OnFinalize = func() string { rl.End(); return "" }

	lp.OnResumeFromStop = func() error {
		rl.Start()
		return nil
	}

	lp.OnResize = func(old_size loop.ScreenSize, new_size loop.ScreenSize) error {
		rl.Redraw()
		return nil
	}

	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		err := rl.OnKeyEvent(event)
		if err != nil {
			if err == io.EOF {
				lp.Quit(0)
				return nil
			}
			if err == readline.ErrAcceptInput {
				if strings.HasSuffix(rl.TextBeforeCursor(), "\\") && strings.HasPrefix(rl.TextAfterCursor(), "\n") {
					rl.OnText("\n", false, false)
					return nil
				}
				return ErrExec
			}
			return err
		}
		if event.Handled {
			rl.Redraw()
			return nil
		}
		return nil
	}

	lp.OnText = func(text string, from_key_event, in_bracketed_paste bool) error {
		err := rl.OnText(text, from_key_event, in_bracketed_paste)
		if err == nil {
			rl.Redraw()
		}
		return err
	}

	err = lp.Run()
	if err != nil {
		return 1, err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		if kill_if_signaled {
			lp.KillIfSignalled()
			return 1, nil
		}
		return 1, fmt.Errorf("Killed by signal: %s", ds)
	}
	return 0, nil
}

func exec_command(cmdline string) bool {
	parsed_cmdline, err := shlex.Split(cmdline)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Could not parse cmdline:", err)
		return true
	}
	if len(parsed_cmdline) == 0 {
		return true
	}
	switch parsed_cmdline[0] {
	case "exit":
		return false
	}
	return true
}

func shell_main(cmd *cli.Command, args []string) (int, error) {
	formatter = markup.New(true)
	fmt.Println("Welcome to the kitty shell!")
	fmt.Println("Use", formatter.Green("help"), "for assistance or", formatter.Green("exit"), "to quit.")
	rl := readline.New(nil, readline.RlInit{Prompt: prompt})
	for {
		rc, err := shell_loop(rl, true)
		if err != nil {
			if err == ErrExec {
				cmdline := rl.AllText()
				cmdline = strings.ReplaceAll(cmdline, "\\\n", "")
				if !exec_command(cmdline) {
					return 0, nil
				}
				continue
			}
		}
		return rc, err
	}
}
