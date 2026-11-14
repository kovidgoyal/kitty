// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tool

import (
	"fmt"

	"github.com/kovidgoyal/datty/daddies/ask"
	"github.com/kovidgoyal/datty/daddies/broadcast"
	"github.com/kovidgoyal/datty/daddies/choose_files"
	"github.com/kovidgoyal/datty/daddies/choose_fonts"
	"github.com/kovidgoyal/datty/daddies/clipboard"
	"github.com/kovidgoyal/datty/daddies/command_palette"
	"github.com/kovidgoyal/datty/daddies/desktop_ui"
	"github.com/kovidgoyal/datty/daddies/diff"
	"github.com/kovidgoyal/datty/daddies/dnd"
	"github.com/kovidgoyal/datty/daddies/hints"
	"github.com/kovidgoyal/datty/daddies/hyperlinked_grep"
	"github.com/kovidgoyal/datty/daddies/icat"
	"github.com/kovidgoyal/datty/daddies/notify"
	"github.com/kovidgoyal/datty/daddies/panel"
	"github.com/kovidgoyal/datty/daddies/query_terminal"
	"github.com/kovidgoyal/datty/daddies/quick_access_terminal"
	"github.com/kovidgoyal/datty/daddies/remote_file"
	"github.com/kovidgoyal/datty/daddies/resize_window"
	"github.com/kovidgoyal/datty/daddies/show_key"
	"github.com/kovidgoyal/datty/daddies/ssh"
	"github.com/kovidgoyal/datty/daddies/themes"
	"github.com/kovidgoyal/datty/daddies/transfer"
	"github.com/kovidgoyal/datty/daddies/unicode_input"
	"github.com/kovidgoyal/datty/tools/cli"
	"github.com/kovidgoyal/datty/tools/cmd/at"
	"github.com/kovidgoyal/datty/tools/cmd/atexit"
	"github.com/kovidgoyal/datty/tools/cmd/benchmark"
	"github.com/kovidgoyal/datty/tools/cmd/edit_in_datty"
	"github.com/kovidgoyal/datty/tools/cmd/mouse_demo"
	"github.com/kovidgoyal/datty/tools/cmd/pytest"
	"github.com/kovidgoyal/datty/tools/cmd/run_shell"
	"github.com/kovidgoyal/datty/tools/cmd/show_error"
	"github.com/kovidgoyal/datty/tools/cmd/update_self"
	"github.com/kovidgoyal/datty/tools/tui"
	"github.com/kovidgoyal/datty/tools/utils/images"
	"github.com/kovidgoyal/datty/tools/watch"
)

var _ = fmt.Print

func DattyToolEntryPoints(root *cli.Command) {
	root.Add(cli.OptionSpec{
		Name: "--version", Type: "bool-set", Help: "The current daddy version."})
	tui.PrepareRootCmd(root)
	// @
	at.EntryPoint(root)
	// update-self
	update_self.EntryPoint(root)
	// edit-in-datty
	edit_in_datty.EntryPoint(root)
	// clipboard
	clipboard.EntryPoint(root)
	// dnd
	dnd.EntryPoint(root)
	// icat
	icat.EntryPoint(root)
	// ssh
	ssh.EntryPoint(root)
	// transfer
	transfer.EntryPoint(root)
	// panel
	panel.EntryPoint(root)
	// quick_access_terminal
	quick_access_terminal.EntryPoint(root)
	// resize_window
	resize_window.EntryPoint(root)
	// broadcast
	broadcast.EntryPoint(root)
	// remote_file
	remote_file.EntryPoint(root)
	// unicode_input
	unicode_input.EntryPoint(root)
	// show_key
	show_key.EntryPoint(root)
	// desktop_ui
	desktop_ui.EntryPoint(root)
	// mouse_demo
	root.AddSubCommand(&cli.Command{
		Name:             "mouse-demo",
		ShortDescription: "Demo the mouse handling datty implements for terminal programs",
		OnlyArgsAllowed:  true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			return mouse_demo.Run(args)
		},
	})
	// hyperlinked_grep
	hyperlinked_grep.EntryPoint(root)
	// ask
	ask.EntryPoint(root)
	// hints
	hints.EntryPoint(root)
	// diff
	diff.EntryPoint(root)
	// notify
	notify.EntryPoint(root)
	// themes
	themes.EntryPoint(root)
	themes.ParseEntryPoint(root)
	// run-shell
	run_shell.EntryPoint(root)
	// show_error
	show_error.EntryPoint(root)
	// choose-fonts
	choose_fonts.EntryPoint(root)
	// choose-files
	choose_files.EntryPoint(root)
	// command-palette
	command_palette.EntryPoint(root)
	// query-terminal
	query_terminal.EntryPoint(root)
	// __pytest__
	pytest.EntryPoint(root)
	// __hold_till_enter__
	root.AddSubCommand(&cli.Command{
		Name:            "__hold_till_enter__",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			return tui.ExecAndHoldTillEnter(args)
		},
	})
	// __shebang__
	root.AddSubCommand(&cli.Command{
		Name:            "__shebang__",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			return run_shebang(args)
		},
	})
	// __confirm_and_run_exe__
	root.AddSubCommand(&cli.Command{
		Name:            "__confirm_and_run_exe__",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			return confirm_and_run_exe(args)
		},
	})
	// __watch_conf__
	watch.EntryPoint(root)
	// __convert_image__
	images.ConvertEntryPoint(root)
	// __atexit__
	atexit.EntryPoint(root)
	// __width_test__
	cli.WcswidthDaddyEntryPoint(root)
	// __generate_man_pages__
	root.AddSubCommand(&cli.Command{
		Name:            "__generate_man_pages__",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			q := root
			if len(args) > 0 {
				for _, scname := range args {
					sc := q.FindSubCommand(scname)
					if sc == nil {
						return 1, fmt.Errorf("No sub command named: %s found", scname)
					}
					if err = sc.GenerateManPages(1, true); err != nil {
						return 1, err
					}
				}
			} else {
				if err = q.GenerateManPages(1, false); err != nil {
					rc = 1
				}
			}
			return
		},
	})
	benchmark.EntryPoint(root)
}
