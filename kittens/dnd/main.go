// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package dnd

import (
	"fmt"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
)

var _ = fmt.Append
var debugprintln = tty.DebugPrintln
var _ = debugprintln

func dnd_main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	return 0, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, dnd_main)
}
