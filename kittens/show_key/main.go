// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package show_key

import (
	"fmt"

	"github.com/kovidgoyal/kitty/tools/cli"
)

var _ = fmt.Print

var runner = struct {
	kitty  func(*Options) error
	legacy func(*Options) error
}{
	kitty:  run_kitty_loop,
	legacy: run_legacy_loop,
}

func main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	if opts.KeyMode == "kitty" {
		err = runner.kitty(opts)
	} else {
		err = runner.legacy(opts)
	}
	if err != nil {
		rc = 1
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
