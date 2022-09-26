// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package main

import (
	"kitty/tools/cli"
	"kitty/tools/cmd/at"
	"kitty/tools/cmd/completion"
)

func main() {
	root := cli.NewRootCommand()
	root.ShortDescription = "Fast, statically compiled implementations for various kitty command-line tools"
	root.Usage = "command [command options] [command args]"

	// @
	at.EntryPoint(root)
	// __complete__
	completion.EntryPoint(root)

	root.Exec()
}
