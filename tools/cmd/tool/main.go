// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tool

import (
	"fmt"

	"kitty/tools/cli"
	"kitty/tools/cmd/at"
	"kitty/tools/cmd/clipboard"
	"kitty/tools/cmd/edit_in_kitty"
	"kitty/tools/cmd/icat"
	"kitty/tools/cmd/pytest"
	"kitty/tools/cmd/ssh"
	"kitty/tools/cmd/unicode_input"
	"kitty/tools/cmd/update_self"
	"kitty/tools/tui"
)

var _ = fmt.Print

func KittyToolEntryPoints(root *cli.Command) {
	root.Add(cli.OptionSpec{
		Name: "--version", Type: "bool-set", Help: "The current kitten version."})
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
	// unicode_input
	unicode_input.EntryPoint(root)
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
}
