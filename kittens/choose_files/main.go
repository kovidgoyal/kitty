package choose_files

import (
	"fmt"
	"os"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print
var debugprintln = tty.DebugPrintln

type State struct {
	Base_dir string
}

type ScreenSize struct {
	width, height, cell_width, cell_height, width_px, height_px int
}

type Handler struct {
	state       State
	screen_size ScreenSize
	lp          *loop.Loop
}

func (h *Handler) draw_screen() (err error) {
	h.lp.StartAtomicUpdate()
	defer h.lp.EndAtomicUpdate()

	return
}

func (h *Handler) OnInitialize() (ans string, err error) {
	h.lp.AllowLineWrapping(false)
	h.lp.SetCursorShape(loop.BAR_CURSOR, true)
	h.draw_screen()
	return
}

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	handler := Handler{lp: lp}
	switch len(args) {
	case 0:
		os.Getwd()
		if handler.state.Base_dir, err = os.Getwd(); err != nil {
			return
		}
	case 1:
		handler.state.Base_dir = args[0]
	default:
		return 1, fmt.Errorf("Can only specify one directory to search in")
	}
	lp.OnInitialize = handler.OnInitialize
	lp.OnResize = func(old, new_size loop.ScreenSize) (err error) {
		handler.screen_size.width = int(new_size.WidthCells)
		handler.screen_size.height = int(new_size.HeightCells)
		handler.screen_size.cell_width = int(new_size.CellWidth)
		handler.screen_size.cell_height = int(new_size.CellHeight)
		handler.screen_size.width_px = int(new_size.WidthPx)
		handler.screen_size.height_px = int(new_size.HeightPx)
		return handler.draw_screen()
	}
	err = lp.Run()
	if err != nil {
		return 1, err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return 1, nil
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
