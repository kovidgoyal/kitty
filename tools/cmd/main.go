// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/datty/daddies/ssh"
	"github.com/kovidgoyal/datty/tools/cli"
	"github.com/kovidgoyal/datty/tools/cmd/completion"
	"github.com/kovidgoyal/datty/tools/cmd/tool"
	"github.com/kovidgoyal/datty/tools/utils"
	"golang.org/x/sys/unix"
)

func DaddyMain(args ...string) int {
	defer utils.WaitForAtexitWorkerToFinish()
	krm := os.Getenv("DATTY_DADDY_RUN_MODULE")
	os.Unsetenv("DATTY_DADDY_RUN_MODULE")
	switch krm {
	case "ssh_askpass":
		return ssh.RunSSHAskpass()
	}
	root := cli.NewRootCommand()
	root.ShortDescription = "Fast, statically compiled implementations of various daddies (command line tools for use with datty)"
	root.HelpText = "daddy serves as a launcher for running individual daddies. Each daddy can be run as :code:`daddy command`. The list of available daddies is given below."
	root.Usage = "command [command options] [command args]"
	root.Run = func(cmd *cli.Command, args []string) (int, error) {
		if len(args) == 0 {
			cmd.ShowHelp()
			return 0, nil
		}
		if strings.HasSuffix(args[0], ".py") {
			exe := utils.DattyExe()
			if !filepath.IsAbs(exe) {
				exe = utils.Which(exe)
			}
			if err := unix.Exec(exe, append([]string{filepath.Base(exe), "+daddy"}, args...), os.Environ()); err != nil {
				return 1, fmt.Errorf("failed to run python daddy: %s as could not run datty executable, with error: %w", args[0], err)
			}
		}
		return 1, fmt.Errorf(":yellow:`%s` is not a known daddy. Use --help to get a list of known daddies.", args[0])
	}

	tool.DattyToolEntryPoints(root)
	completion.EntryPoint(root)

	root.SubCommandIsOptional = true
	return root.ExecArgs(args)
}

func main() {
	os.Exit(DaddyMain())
}
