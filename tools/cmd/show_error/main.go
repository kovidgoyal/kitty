// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package show_error

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print

type Options struct {
	Title string
}

type Message struct {
	Msg       string `json:"msg"`
	Traceback string `json:"tb"`
}

func main(args []string, opts *Options) (rc int, err error) {
	if tty.IsTerminal(os.Stdin.Fd()) {
		return 1, fmt.Errorf("Input data for this kitten must be piped as JSON to STDIN")
	}
	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		return 1, err
	}
	m := Message{}
	err = json.Unmarshal(data, &m)
	if err != nil {
		return 1, err
	}
	f := markup.New(true)
	if opts.Title != "" {
		fmt.Println(f.Err(opts.Title))
		fmt.Println(loop.EscapeCodeToSetWindowTitle(opts.Title))
		fmt.Println()
	}
	fmt.Println(m.Msg)
	show_traceback := false
	if m.Traceback != "" {
		lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
		if err != nil {
			return 1, err
		}
		lp.OnInitialize = func() (string, error) {
			lp.SetCursorVisible(false)
			lp.QueueWriteString("\n\r\x1b[1;32mPress e to see detailed traceback or any other key to exit\x1b[m\r\n")
			return "", nil
		}
		lp.OnFinalize = func() string {
			lp.SetCursorVisible(true)
			return ""
		}

		lp.OnKeyEvent = func(event *loop.KeyEvent) error {
			if event.Type == loop.PRESS || event.Type == loop.REPEAT {
				if event.MatchesPressOrRepeat("e") || event.MatchesPressOrRepeat("shift+e") || event.MatchesPressOrRepeat("E") {
					show_traceback = true
					lp.Quit(0)
				} else {
					lp.Quit(1)
				}
			}
			if event.MatchesPressOrRepeat("enter") || event.MatchesPressOrRepeat("kp_enter") || event.MatchesPressOrRepeat("esc") || event.MatchesPressOrRepeat("ctrl+c") || event.MatchesPressOrRepeat("ctrl+d") {
				event.Handled = true
				lp.Quit(0)
			}
			return nil
		}
		lp.Run()
		if lp.ExitCode() == 1 {
			return 0, nil
		}
	}
	if show_traceback {
		fmt.Println(m.Traceback)
		fmt.Println()
	}
	tui.HoldTillEnter(true)
	return
}

func EntryPoint(root *cli.Command) *cli.Command {
	sc := root.AddSubCommand(&cli.Command{
		Name:             "__show_error__",
		Hidden:           true,
		Usage:            "[options]",
		ShortDescription: "Show an error message. Internal use.",
		HelpText:         "Show an error message. Used internally by kitty.",
		Run: func(cmd *cli.Command, args []string) (ret int, err error) {
			opts := &Options{}
			err = cmd.GetOptionValues(opts)
			if err != nil {
				return 1, err
			}
			return main(args, opts)
		},
	})
	sc.Add(cli.OptionSpec{
		Name:    "--title",
		Default: "ERROR",
		Help:    "The title for the error message",
	})
	return sc
}
