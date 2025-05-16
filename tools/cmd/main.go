// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package main

import (
	"os"

	"github.com/kovidgoyal/kitty/kittens/ssh"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cmd/completion"
	"github.com/kovidgoyal/kitty/tools/cmd/tool"
)

func KittenMain(args ...string) {
	krm := os.Getenv("KITTY_KITTEN_RUN_MODULE")
	os.Unsetenv("KITTY_KITTEN_RUN_MODULE")
	switch krm {
	case "ssh_askpass":
		ssh.RunSSHAskpass()
		return
	}
	root := cli.NewRootCommand()
	root.ShortDescription = "Fast, statically compiled implementations of various kittens (command line tools for use with kitty)"
	root.HelpText = "kitten serves as a launcher for running individual kittens. Each kitten can be run as :code:`kitten command`. The list of available kittens is given below."
	root.Usage = "command [command options] [command args]"
	root.Run = func(cmd *cli.Command, args []string) (int, error) {
		cmd.ShowHelp()
		return 0, nil
	}

	tool.KittyToolEntryPoints(root)
	completion.EntryPoint(root)

	root.Exec(args...)
}

func main() {
	KittenMain()
}
