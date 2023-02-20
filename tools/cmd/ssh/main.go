// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"errors"
	"fmt"
	"os"
	"strings"

	"kitty/tools/cli"

	"golang.org/x/exp/maps"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func main(cmd *cli.Command, o *Options, args []string) (rc int, err error) {
	if len(args) > 0 {
		switch args[0] {
		case "use-python":
			args = args[1:] // backwards compat from when we had a python implementation
		case "-h", "--help":
			cmd.ShowHelp()
			return
		}
	}
	ssh_args, server_args, passthrough, found_extra_args, err := ParseSSHArgs(args, "--kitten")
	if err != nil {
		var invargs *ErrInvalidSSHArgs
		switch {
		case errors.As(err, &invargs):
			if invargs.Msg != "" {
				fmt.Fprintln(os.Stderr, invargs.Msg)
			}
			return 1, unix.Exec(ssh_exe(), []string{"ssh"}, os.Environ())
		}
		return 1, err
	}
	if passthrough {
		if len(found_extra_args) > 0 {
			return 1, fmt.Errorf("The SSH kitten cannot work with the options: %s", strings.Join(maps.Keys(PassthroughArgs()), " "))
		}
		return 1, unix.Exec(ssh_exe(), append([]string{"ssh"}, args...), os.Environ())
	}
	if false {
		return len(ssh_args) + len(server_args), nil
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}

func specialize_command(ssh *cli.Command) {
	ssh.Usage = "arguments for the ssh command"
	ssh.ShortDescription = "Truly convenient SSH"
	ssh.HelpText = "The ssh kitten is a thin wrapper around the ssh command. It automatically enables shell integration on the remote host, re-uses existing connections to reduce latency, makes the kitty terminfo database available, etc. It's invocation is identical to the ssh command. For details on its usage, see :doc:`/kittens/ssh`."
	ssh.IgnoreAllArgs = true
	ssh.OnlyArgsAllowed = true
	ssh.ArgCompleter = cli.CompletionForWrapper("ssh")
}
