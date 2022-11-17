// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tool

import (
	"fmt"
	"kitty/tools/cli"
	"kitty/tools/cmd/at"
	"kitty/tools/cmd/edit_in_kitty"
	"kitty/tools/cmd/update_self"
)

var _ = fmt.Print

func KittyToolEntryPoints(root *cli.Command) {
	root.Add(cli.OptionSpec{
		Name: "--version", Type: "bool-set", Help: "The current kitty version."})
	// @
	at.EntryPoint(root)
	// update-self
	update_self.EntryPoint(root)
	// edit-in-kitty
	edit_in_kitty.EntryPoint(root)
}
