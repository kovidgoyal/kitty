// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"fmt"

	"kitty/tools/cli"
)

var _ = fmt.Print

func main(cmd *cli.Command, o *Options, args []string) (rc int, err error) {
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
}
