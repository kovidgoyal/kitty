// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"fmt"

	"kitty/tools/cli"
)

func clipboard_main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	if len(args) > 0 {
		return 1, fmt.Errorf("Unrecognized extra command line arguments")
	}

	return 0, run_plain_text_loop(opts)
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, clipboard_main)
}
