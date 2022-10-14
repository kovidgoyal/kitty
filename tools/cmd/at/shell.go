// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/shlex"

	"kitty/tools/cli"
	"kitty/tools/cli/markup"
	"kitty/tools/tui/loop"
	"kitty/tools/tui/readline"
	"kitty/tools/utils"
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
				if strings.HasSuffix(rl.TextBeforeCursor(), "\\") && rl.CursorAtEndOfLine() {
					rl.OnText("\n", false, false)
					rl.Redraw()
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

func print_basic_help() {
	fmt.Println("Control kitty by sending it commands.")
	fmt.Println()
	fmt.Println(formatter.Title("Commands") + ":")
	r := EntryPoint(cli.NewRootCommand())
	for _, g := range r.SubCommandGroups {
		for _, sc := range g.SubCommands {
			fmt.Println(" ", formatter.Green(sc.Name))
			fmt.Println("   ", sc.ShortDescription)
		}
	}
	fmt.Println(" ", formatter.Green("exit"))
	fmt.Println("   ", "Exit this shell")
}

func exec_command(rl *readline.Readline, cmdline string) bool {
	parsed_cmdline, err := shlex.Split(cmdline)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Could not parse cmdline:", err)
		return true
	}
	if len(parsed_cmdline) == 0 {
		return true
	}
	hi := readline.HistoryItem{Timestamp: time.Now(), Cmd: cmdline, ExitCode: -1}
	switch parsed_cmdline[0] {
	case "exit":
		hi.ExitCode = 0
		rl.AddHistoryItem(hi)
		return false
	case "help":
		hi.ExitCode = 0
		defer rl.AddHistoryItem(hi)
		if len(parsed_cmdline) == 1 {
			print_basic_help()
			return true
		}
		switch parsed_cmdline[1] {
		case "exit":
			fmt.Println("Exit this shell")
		case "help":
			fmt.Println("Show help")
		default:
			r := EntryPoint(cli.NewRootCommand())
			sc := r.FindSubCommand(parsed_cmdline[1])
			if sc == nil {
				hi.ExitCode = 1
				fmt.Fprintln(os.Stderr, "No command named", formatter.BrightRed(parsed_cmdline[1]), ". Type help for a list of commands")
			} else {
				sc.ShowHelpWithCommandString(sc.Name)
			}
		}
		return true
	default:
		exe, err := os.Executable()
		if err != nil {
			exe, err = exec.LookPath("kitty-tool")
			if err != nil {
				fmt.Fprintln(os.Stderr, "Could not find the kitty-tool executable")
				return false
			}
		}
		cmdline := []string{"kitty-tool", "@"}
		cmdline = append(cmdline, parsed_cmdline...)
		cmd := exec.Cmd{Path: exe, Args: cmdline, Stdin: os.Stdin, Stdout: os.Stdout, Stderr: os.Stderr}
		err = cmd.Run()
		hi.Duration = time.Now().Sub(hi.Timestamp)
		hi.ExitCode = 0
		if err != nil {
			if exitError, ok := err.(*exec.ExitError); ok {
				hi.ExitCode = exitError.ExitCode()
			}
			fmt.Fprintln(os.Stderr, err)
		}
		rl.AddHistoryItem(hi)
	}
	return true
}

func shell_main(cmd *cli.Command, args []string) (int, error) {
	formatter = markup.New(true)
	fmt.Println("Welcome to the kitty shell!")
	fmt.Println("Use", formatter.Green("help"), "for assistance or", formatter.Green("exit"), "to quit.")
	rl := readline.New(nil, readline.RlInit{Prompt: prompt, HistoryPath: filepath.Join(utils.CacheDir(), "shell.history.json")})
	defer func() {
		rl.Shutdown()
	}()
	for {
		rc, err := shell_loop(rl, true)
		if err != nil {
			if err == ErrExec {
				cmdline := rl.AllText()
				cmdline = strings.ReplaceAll(cmdline, "\\\n", "")
				if !exec_command(rl, cmdline) {
					return 0, nil
				}
				continue
			}
		}
		return rc, err
	}
}
