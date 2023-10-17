// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package mouse_demo

import (
	"fmt"

	"kitty/tools/tui/loop"
)

var _ = fmt.Print

func Run(args []string) (rc int, err error) {
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	lp.MouseTrackingMode(loop.FULL_MOUSE_TRACKING)
	var current_mouse_event *loop.MouseEvent

	draw_screen := func() {
		lp.StartAtomicUpdate()
		defer lp.EndAtomicUpdate()
		if current_mouse_event == nil {
			lp.Println(`Move the mouse or click to see mouse events`)
			return
		}
		lp.ClearScreen()
		lp.Printf("Position: %d, %d (pixels)\r\n", current_mouse_event.Pixel.X, current_mouse_event.Pixel.Y)
		lp.Printf("Cell    : %d, %d\r\n", current_mouse_event.Cell.X, current_mouse_event.Cell.Y)
		lp.Printf("Type    : %s\r\n", current_mouse_event.Event_type)
		if current_mouse_event.Buttons != loop.NO_MOUSE_BUTTON {
			lp.Println(current_mouse_event.Buttons.String())
		}
		if mods := current_mouse_event.Mods.String(); mods != "" {
			lp.Printf("Modifiers: %s\r\n", mods)
		}
	}

	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		draw_screen()
		return "", nil
	}
	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		return ""
	}

	lp.OnMouseEvent = func(ev *loop.MouseEvent) error {
		current_mouse_event = ev
		draw_screen()
		return nil
	}
	lp.OnKeyEvent = func(ev *loop.KeyEvent) error {
		if ev.MatchesPressOrRepeat("esc") || ev.MatchesPressOrRepeat("ctrl+c") {
			lp.Quit(0)
		}
		return nil
	}
	err = lp.Run()
	if err != nil {
		rc = 1
	}
	return
}
