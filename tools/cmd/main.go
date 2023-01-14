// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package main

import (
	"kitty/tools/cli"
	"kitty/tools/cmd/completion"
	"kitty/tools/cmd/tool"
)

func main() {
	root := cli.NewRootCommand()
	root.ShortDescription = "Fast, statically compiled implementations for various kittens (command line tools for use with kitty)"
	root.Usage = "command [command options] [command args]"
	root.Run = func(cmd *cli.Command, args []string) (int, error) {
		cmd.ShowHelp()
		return 0, nil
	}

	tool.KittyToolEntryPoints(root)
	completion.EntryPoint(root)

	root.Exec()
}
