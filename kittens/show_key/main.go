// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package show_key

import (
	"fmt"

	"github.com/kovidgoyal/kitty/tools/cli"
)

var _ = fmt.Print

func main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	if opts.KeyMode == "kitty" {
		err = run_kitty_loop(opts)
	} else {
		err = run_legacy_loop(opts)
	}
	if err != nil {
		rc = 1
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
