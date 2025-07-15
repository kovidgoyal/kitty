// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/kittens/ssh"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cmd/completion"
	"github.com/kovidgoyal/kitty/tools/cmd/tool"
	"github.com/kovidgoyal/kitty/tools/utils"
	"golang.org/x/sys/unix"
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
		if len(args) == 0 {
			cmd.ShowHelp()
			return 0, nil
		}
		if strings.HasSuffix(args[0], ".py") {
			exe := utils.KittyExe()
			if !filepath.IsAbs(exe) {
				exe = utils.Which(exe)
			}
			if err := unix.Exec(exe, append([]string{filepath.Base(exe), "+kitten"}, args...), os.Environ()); err != nil {
				return 1, fmt.Errorf("failed to run python kitten: %s as could not run kitty executable, with error: %w", args[0], err)
			}
		}
		return 1, fmt.Errorf(":yellow:`%s` is not a known kitten. Use --help to get a list of known kittens.", args[0])
	}

	tool.KittyToolEntryPoints(root)
	completion.EntryPoint(root)

	root.SubCommandIsOptional = true
	root.Exec(args...)
}

func main() {
	KittenMain()
}
