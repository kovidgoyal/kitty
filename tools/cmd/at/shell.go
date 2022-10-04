// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"fmt"

	"kitty/tools/cli"
	"kitty/tools/cli/markup"
	"kitty/tools/tui/loop"
	"kitty/tools/tui/readline"
)

var _ = fmt.Print

var formatter *markup.Context

const prompt = "🐱 "

func shell_loop(kill_if_signaled bool) (int, error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return 1, err
	}
	rl := readline.New(lp, readline.RlInit{Prompt: prompt})

	lp.OnInitialize = func() (string, error) {
		rl.Start()
		return "\r\n", nil
	}

	lp.OnResumeFromStop = func() error {
		rl.Start()
		return nil
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

func shell_main(cmd *cli.Command, args []string) (int, error) {
	formatter = markup.New(true)
	fmt.Println("Welcome to the kitty shell!")
	fmt.Println("Use", formatter.Green("help"), "for assistance or", formatter.Green("exit"), "to quit.")
	return shell_loop(true)
}
