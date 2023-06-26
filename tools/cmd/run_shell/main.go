// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package run_shell

import (
	"fmt"

	"kitty/tools/cli"
	"kitty/tools/tui"
)

var _ = fmt.Print

type Options struct {
	Shell            string
	ShellIntegration string
}

func main(args []string, opts *Options) (rc int, err error) {
	if len(args) > 0 {
		tui.RunCommandRestoringTerminalToSaneStateAfter(args)
	}
	err = tui.RunShell(tui.ResolveShell(opts.Shell), tui.ResolveShellIntegration(opts.ShellIntegration))
	if err != nil {
		rc = 1
	}
	return
}

func EntryPoint(root *cli.Command) *cli.Command {
	sc := root.AddSubCommand(&cli.Command{
		Name:             "run-shell",
		Usage:            "[options] [optional cmd to run before running the shell ...]",
		ShortDescription: "Run the user's shell with shell integration enabled",
		HelpText:         "Run the users's configured shell. If the shell supports shell integration, enable it based on the user's configured shell_integration setting.",
		Run: func(cmd *cli.Command, args []string) (ret int, err error) {
			opts := &Options{}
			err = cmd.GetOptionValues(opts)
			if err != nil {
				return 1, err
			}
			return main(args, opts)
		},
	})
	sc.Add(cli.OptionSpec{
		Name: "--shell-integration",
		Help: "Specify a value for the :opt:`shell_integration` option, overriding the one from :file:`kitty.conf`.",
	})
	sc.Add(cli.OptionSpec{
		Name:    "--shell",
		Default: ".",
		Help:    "Specify the shell command to run. The default value of :code:`.` will use the parent shell if recognized, falling back to the value of the :opt:`shell` option from :file:`kitty.conf`.",
	})
	return sc
}
