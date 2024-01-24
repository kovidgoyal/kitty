// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package run_shell

import (
	"fmt"
	"kitty"
	"os"
	"strings"

	"kitty/tools/cli"
	"kitty/tools/tty"
	"kitty/tools/tui"
	"kitty/tools/tui/shell_integration"
)

var _ = fmt.Print

type Options struct {
	Shell            string
	ShellIntegration string
	Env              []string
	Cwd              string
}

func main(args []string, opts *Options) (rc int, err error) {
	if len(args) > 0 {
		tui.RunCommandRestoringTerminalToSaneStateAfter(args)
	}
	env_before := os.Environ()
	changed := false
	for _, entry := range opts.Env {
		k, v, found := strings.Cut(entry, "=")
		if found {
			if err := os.Setenv(k, v); err != nil {
				return 1, fmt.Errorf("Failed to set the env var %s with error: %w", k, err)
			}
		} else {
			if err := os.Unsetenv(k); err != nil {
				return 1, fmt.Errorf("Failed to unset the env var %s with error: %w", k, err)
			}
		}
		changed = true
	}
	if os.Getenv("TERM") == "" {
		os.Setenv("TERM", kitty.DefaultTermName)
	}
	if term := os.Getenv("TERM"); term == kitty.DefaultTermName && shell_integration.PathToTerminfoDb(term) == "" {
		if terminfo_dir, err := shell_integration.EnsureTerminfoFiles(); err == nil {
			os.Unsetenv("TERMINFO")
			existing := os.Getenv("TERMINFO_DIRS")
			if existing != "" {
				existing = string(os.PathListSeparator) + existing
			}
			os.Setenv("TERMINFO_DIRS", terminfo_dir+existing)
		}
	}
	err = tui.RunShell(tui.ResolveShell(opts.Shell), tui.ResolveShellIntegration(opts.ShellIntegration), opts.Cwd)
	if changed {
		os.Clearenv()
		for _, entry := range env_before {
			k, v, _ := strings.Cut(entry, "=")
			os.Setenv(k, v)
		}
	}
	if err != nil {
		rc = 1
	}
	return
}

var debugprintln = tty.DebugPrintln
var _ = debugprintln

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
	sc.Add(cli.OptionSpec{
		Name: "--env",
		Help: "Specify an env var to set before running the shell. Of the form KEY=VAL. Can be specified multiple times. If no = is present KEY is unset.",
		Type: "list",
	})
	sc.Add(cli.OptionSpec{
		Name: "--cwd",
		Help: "The working directory to use when executing the shell.",
	})

	return sc
}
