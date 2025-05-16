// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package show_key

import (
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print

func csi(csi string) string {
	return "CSI " + strings.NewReplacer(":", " : ", ";", " ; ").Replace(csi[:len(csi)-1]) + " " + csi[len(csi)-1:]
}

func run_kitty_loop(_ *Options) (err error) {
	lp, err := loop.New(loop.FullKeyboardProtocol)
	if err != nil {
		return err
	}
	ctx := markup.New(true)

	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		lp.SetWindowTitle("kitty extended keyboard protocol demo")
		lp.Println("Press any keys - Ctrl+C or Ctrl+D will terminate")
		return "", nil
	}

	lp.OnKeyEvent = func(e *loop.KeyEvent) (err error) {
		e.Handled = true
		if e.MatchesPressOrRepeat("ctrl+c") || e.MatchesPressOrRepeat("ctrl+d") {
			lp.Quit(0)
			return
		}
		mods := e.Mods.String()
		if mods != "" {
			mods += "+"
		}
		etype := e.Type.String()
		key := e.Key
		if key == " " {
			key = "space"
		}
		key = mods + key
		lp.Printf("%s %s %s\r\n", ctx.Green(key), ctx.Yellow(etype), e.Text)
		lp.Println(ctx.Cyan(csi(e.CSI)))
		if e.AlternateKey != "" || e.ShiftedKey != "" {
			if e.ShiftedKey != "" {
				lp.QueueWriteString(ctx.Dim("Shifted key: "))
				lp.QueueWriteString(e.ShiftedKey + " ")
			}
			if e.AlternateKey != "" {
				lp.QueueWriteString(ctx.Dim("Alternate key: "))
				lp.QueueWriteString(e.AlternateKey + " ")
			}
			lp.Println()
		}
		lp.Println()
		return
	}
	lp.OnText = func(text string, from_key_event bool, in_bracketed_paste bool) error {
		if from_key_event {
			return nil
		}
		lp.Printf("%s: %s\n\n", ctx.Green("Text"), text)
		return nil
	}

	err = lp.Run()
	if err != nil {
		return
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return
	}

	return
}
