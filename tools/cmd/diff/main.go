// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"

	"kitty/tools/cli"
)

var _ = fmt.Print

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
