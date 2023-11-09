// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tool

import (
	"fmt"

	"kitty/kittens/ask"
	"kitty/kittens/clipboard"
	"kitty/kittens/diff"
	"kitty/kittens/hints"
	"kitty/kittens/hyperlinked_grep"
	"kitty/kittens/icat"
	"kitty/kittens/show_key"
	"kitty/kittens/ssh"
	"kitty/kittens/themes"
	"kitty/kittens/transfer"
	"kitty/kittens/unicode_input"
	"kitty/tools/cli"
	"kitty/tools/cmd/at"
	"kitty/tools/cmd/benchmark"
	"kitty/tools/cmd/edit_in_kitty"
	"kitty/tools/cmd/mouse_demo"
	"kitty/tools/cmd/pytest"
	"kitty/tools/cmd/run_shell"
	"kitty/tools/cmd/show_error"
	"kitty/tools/cmd/update_self"
	"kitty/tools/tui"
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
	// unicode_input
	unicode_input.EntryPoint(root)
	// show_key
	show_key.EntryPoint(root)
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
	// hints
	diff.EntryPoint(root)
	// themes
	themes.EntryPoint(root)
	themes.ParseEntryPoint(root)
	// run-shell
	run_shell.EntryPoint(root)
	// show_error
	show_error.EntryPoint(root)
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
	// __confirm_and_run_shebang__
	root.AddSubCommand(&cli.Command{
		Name:            "__confirm_and_run_shebang__",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			return confirm_and_run_shebang(args)
		},
	})
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
