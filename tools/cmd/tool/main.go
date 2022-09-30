// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tool

import (
	"fmt"
	"kitty/tools/cli"
	"kitty/tools/cmd/at"
)

var _ = fmt.Print

func KittyToolEntryPoints(root *cli.Command) {
	// @
	at.EntryPoint(root)

}
