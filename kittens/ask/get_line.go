// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ask

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func get_line(o *Options) (result string, err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return
	}
	cwd, _ := os.Getwd()
	ropts := readline.RlInit{Prompt: o.Prompt}
	if o.Name != "" {
		base := filepath.Join(utils.CacheDir(), "ask")
		ropts.HistoryPath = filepath.Join(base, o.Name+".history.json")
		os.MkdirAll(base, 0o755)
	}
	rl := readline.New(lp, ropts)
	if o.Default != "" {
		rl.SetText(o.Default)
	}
	lp.OnInitialize = func() (string, error) {
		rl.Start()
		return "", nil
	}
	lp.OnFinalize = func() string { rl.End(); return "" }

	lp.OnResumeFromStop = func() error {
		rl.Start()
		return nil
	}

	lp.OnResize = rl.OnResize

	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("ctrl+c") {
			return fmt.Errorf("Canceled by user")
		}
		err := rl.OnKeyEvent(event)
		if err != nil {
			if err == io.EOF {
				lp.Quit(0)
				return nil
			}
			if err == readline.ErrAcceptInput {
				hi := readline.HistoryItem{Timestamp: time.Now(), Cmd: rl.AllText(), ExitCode: 0, Cwd: cwd}
				rl.AddHistoryItem(hi)
				result = rl.AllText()
				lp.Quit(0)
				return nil
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
	rl.Shutdown()
	if err != nil {
		return "", err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		return "", fmt.Errorf("Killed by signal: %s", ds)
	}
	return
}
