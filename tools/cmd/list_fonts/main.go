package list_fonts

import (
	"encoding/json"
	"fmt"
	"os"

	"kitty/tools/cli"
	"kitty/tools/tty"
	"kitty/tools/tui/loop"
)

var _ = fmt.Print
var debugprintln = tty.DebugPrintln
var json_decoder *json.Decoder

func main() (rc int, err error) {
	json_decoder = json.NewDecoder(os.Stdin)
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	h := &handler{lp: lp}
	lp.OnInitialize = func() (string, error) {
		lp.AllowLineWrapping(false)
		lp.SetWindowTitle(`Choose a font for kitty`)
		h.initialize()
		return "", nil
	}
	lp.OnWakeup = h.on_wakeup
	lp.OnFinalize = func() string {
		h.finalize()
		lp.SetCursorVisible(true)
		return ``
	}
	lp.OnResize = func(_, _ loop.ScreenSize) error {
		return h.draw_screen()
	}
	lp.OnKeyEvent = h.on_key_event
	lp.OnText = h.on_text
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
	return lp.ExitCode(), nil
}

func EntryPoint(root *cli.Command) {
	root = root.AddSubCommand(&cli.Command{
		Name:   "__list_fonts__",
		Hidden: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			return main()
		},
	})
}
