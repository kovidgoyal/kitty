// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tool

import (
	"fmt"

	"github.com/kovidgoyal/kitty/kittens/ask"
	"github.com/kovidgoyal/kitty/kittens/choose_files"
	"github.com/kovidgoyal/kitty/kittens/choose_fonts"
	"github.com/kovidgoyal/kitty/kittens/clipboard"
	"github.com/kovidgoyal/kitty/kittens/desktop_ui"
	"github.com/kovidgoyal/kitty/kittens/diff"
	"github.com/kovidgoyal/kitty/kittens/hints"
	"github.com/kovidgoyal/kitty/kittens/hyperlinked_grep"
	"github.com/kovidgoyal/kitty/kittens/icat"
	"github.com/kovidgoyal/kitty/kittens/notify"
	"github.com/kovidgoyal/kitty/kittens/panel"
	"github.com/kovidgoyal/kitty/kittens/query_terminal"
	"github.com/kovidgoyal/kitty/kittens/quick_access_terminal"
	"github.com/kovidgoyal/kitty/kittens/show_key"
	"github.com/kovidgoyal/kitty/kittens/ssh"
	"github.com/kovidgoyal/kitty/kittens/themes"
	"github.com/kovidgoyal/kitty/kittens/transfer"
	"github.com/kovidgoyal/kitty/kittens/unicode_input"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cmd/at"
	"github.com/kovidgoyal/kitty/tools/cmd/atexit"
	"github.com/kovidgoyal/kitty/tools/cmd/benchmark"
	"github.com/kovidgoyal/kitty/tools/cmd/edit_in_kitty"
	"github.com/kovidgoyal/kitty/tools/cmd/mouse_demo"
	"github.com/kovidgoyal/kitty/tools/cmd/pytest"
	"github.com/kovidgoyal/kitty/tools/cmd/run_shell"
	"github.com/kovidgoyal/kitty/tools/cmd/show_error"
	"github.com/kovidgoyal/kitty/tools/cmd/update_self"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/utils/images"
)

var _ = fmt.Print

func KittyToolEntryPoints(root *cli.Command) {
	root.Add(cli.OptionSpec{
		Name: "--version", Type: "bool-set", Help: "The current kitten version."})
	tui.PrepareRootCmd(root)
	// @
	at.EntryPoint(root)
	// update-self
	update_self.EntryPoint(root)
	// edit-in-kitty
	edit_in_kitty.EntryPoint(root)
	// clipboard
	clipboard.EntryPoint(root)
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
	// unicode_input
	unicode_input.EntryPoint(root)
	// show_key
	show_key.EntryPoint(root)
	// desktop_ui
	desktop_ui.EntryPoint(root)
	// mouse_demo
	root.AddSubCommand(&cli.Command{
		Name:             "mouse-demo",
		ShortDescription: "Demo the mouse handling kitty implements for terminal programs",
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
			tui.ExecAndHoldTillEnter(args)
			return
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

	// __convert_image__
	images.ConvertEntryPoint(root)
	// __atexit__
	atexit.EntryPoint(root)
	// __width_test__
	cli.WcswidthKittenEntryPoint(root)
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
