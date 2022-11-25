// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"fmt"
	"kitty/tools/cli"
)

var _ = fmt.Print

func clipboard_main(cmd *cli.Command, args []string) (int, error) {
	return 0, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, clipboard_main)
}
