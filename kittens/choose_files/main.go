package choose_files

import (
	"fmt"
	"os"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print
var debugprintln = tty.DebugPrintln

type State struct {
	base_dir    string
	current_dir string
	select_dirs bool
	multiselect bool
	max_depth   int
	search_text string
}

func (s State) BaseDir() string    { return utils.IfElse(s.base_dir == "", default_cwd, s.base_dir) }
func (s State) SelectDirs() bool   { return s.select_dirs }
func (s State) Multiselect() bool  { return s.multiselect }
func (s State) MaxDepth() int      { return utils.IfElse(s.max_depth < 1, 5, s.max_depth) }
func (s State) String() string     { return utils.Repr(s) }
func (s State) SearchText() string { return s.search_text }
func (s State) CurrentDir() string {
	return utils.IfElse(s.current_dir == "", s.BaseDir(), s.current_dir)
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
	h.lp.ClearScreen()
	y := 0
	if dy, err := h.draw_search_bar(y); err != nil {
		return err
	} else {
		y += dy
	}

	return
}

func (h *Handler) init_sizes(new_size loop.ScreenSize) {
	h.screen_size.width = int(new_size.WidthCells)
	h.screen_size.height = int(new_size.HeightCells)
	h.screen_size.cell_width = int(new_size.CellWidth)
	h.screen_size.cell_height = int(new_size.CellHeight)
	h.screen_size.width_px = int(new_size.WidthPx)
	h.screen_size.height_px = int(new_size.HeightPx)
}

func (h *Handler) OnInitialize() (ans string, err error) {
	if sz, err := h.lp.ScreenSize(); err != nil {
		return "", err
	} else {
		h.init_sizes(sz)
	}
	h.lp.AllowLineWrapping(false)
	h.lp.SetCursorShape(loop.BAR_CURSOR, true)
	h.draw_screen()
	return
}

var default_cwd string

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	handler := Handler{lp: lp}
	switch len(args) {
	case 0:
		os.Getwd()
		if default_cwd, err = os.Getwd(); err != nil {
			return
		}
	case 1:
		default_cwd = args[0]
	default:
		return 1, fmt.Errorf("Can only specify one directory to search in")
	}
	lp.OnInitialize = handler.OnInitialize
	lp.OnResize = func(old, new_size loop.ScreenSize) (err error) {
		handler.init_sizes(new_size)
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
