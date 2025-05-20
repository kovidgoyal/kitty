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

type Handler struct {
	lp               *loop.Loop
	Current_base_dir string
}

func (h *Handler) OnInitialize() (ans string, err error) {
	return
}

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	cwd := ""
	switch len(args) {
	case 0:
		os.Getwd()
		if cwd, err = os.Getwd(); err != nil {
			return
		}
	case 1:
		cwd = args[0]
	default:
		return 1, fmt.Errorf("Can only specify one directory to search in")
	}
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	handler := Handler{Current_base_dir: cwd, lp: lp}
	lp.OnInitialize = handler.OnInitialize
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
