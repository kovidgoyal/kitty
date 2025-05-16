package choose_fonts

import (
	"fmt"
	"os"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print
var debugprintln = tty.DebugPrintln
var output_on_exit string

func main(opts *Options) (rc int, err error) {
	if err = kitty_font_backend.start(); err != nil {
		return 1, err
	}
	defer func() {
		if werr := kitty_font_backend.release(); werr != nil {
			if err == nil {
				err = werr
			}
			if rc == 0 {
				rc = 1
			}
		}
	}()
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	lp.MouseTrackingMode(loop.FULL_MOUSE_TRACKING)
	h := &handler{lp: lp, opts: opts}
	lp.OnInitialize = func() (string, error) {
		lp.AllowLineWrapping(false)
		lp.SetWindowTitle(`Choose a font for kitty`)
		return "", h.initialize()
	}
	lp.OnWakeup = h.on_wakeup
	lp.OnEscapeCode = h.on_escape_code
	lp.OnFinalize = func() string {
		h.finalize()
		lp.SetCursorVisible(true)
		return ``
	}
	lp.OnMouseEvent = h.on_mouse_event
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
	if output_on_exit != "" {
		os.Stdout.WriteString(output_on_exit)
	}
	return lp.ExitCode(), nil
}

type Options struct {
	Reload_in        string
	Config_file_name string
}

func EntryPoint(root *cli.Command) {
	ans := root.AddSubCommand(&cli.Command{
		Name:             "choose-fonts",
		ShortDescription: "Choose the fonts used in kitty",
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			opts := Options{}
			if err = cmd.GetOptionValues(&opts); err != nil {
				return 1, err
			}
			return main(&opts)
		},
	})
	ans.Add(cli.OptionSpec{
		Name:    "--reload-in",
		Dest:    "Reload_in",
		Type:    "choices",
		Choices: "parent, all, none",
		Default: "parent",
		Help: `By default, this kitten will signal only the parent kitty instance it is
running in to reload its config, after making changes. Use this option to
instead either not reload the config at all or in all running kitty instances.`,
	})
	ans.Add(cli.OptionSpec{
		Name:    "--config-file-name",
		Dest:    "Config_file_name",
		Type:    "str",
		Default: "kitty.conf",
		Help: `The name or path to the config file to edit. Relative paths are interpreted
with respect to the kitty config directory. By default the kitty config
file, kitty.conf is edited. This is most useful if you add include
fonts.conf to your kitty.conf and then have the kitten operate only on
fonts.conf, allowing kitty.conf to remain unchanged.`,
	})

	clone := root.AddClone(ans.Group, ans)
	clone.Hidden = true
	clone.Name = "choose_fonts"
}
