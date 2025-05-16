package query_terminal

import (
	"bytes"
	"fmt"
	"github.com/kovidgoyal/kitty"
	"os"
	"slices"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print

func main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	queries := kitty.QueryNames
	if len(args) > 0 && !slices.Contains(args, "all") {
		queries = make([]string, len(args))
		for i, x := range args {
			if !slices.Contains(kitty.QueryNames, x) {
				return 1, fmt.Errorf("Unknown query: %s", x)
			}
			queries[i] = x
		}
	}
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoKeyboardStateChange, loop.NoMouseTracking, loop.NoRestoreColors, loop.NoInBandResizeNotifications)
	if err != nil {
		return 1, err
	}
	timed_out := false
	lp.OnInitialize = func() (string, error) {
		lp.QueryTerminal(queries...)
		lp.QueueWriteString("\x1b[c")
		_, err := lp.AddTimer(time.Duration(opts.WaitFor*float64(time.Second)), false, func(timer_id loop.IdType) error {
			timed_out = true
			lp.Quit(1)
			return nil
		})

		return "", err
	}
	buf := strings.Builder{}

	lp.OnQueryResponse = func(key, val string, found bool) error {
		if found {
			fmt.Fprintf(&buf, "%s: %s\n", key, val)
		} else {
			fmt.Fprintf(&buf, "%s:\n", key)
		}
		return nil
	}
	lp.OnEscapeCode = func(typ loop.EscapeCodeType, data []byte) error {
		if typ == loop.CSI && bytes.HasSuffix(data, []byte{'c'}) {
			lp.Quit(0)
		}
		return nil
	}
	err = lp.Run()
	rc = lp.ExitCode()
	if err != nil {
		return 1, err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return
	}
	os.Stdout.WriteString(buf.String())

	if timed_out {
		return 1, fmt.Errorf("timed out waiting for response from terminal")
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
