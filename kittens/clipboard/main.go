// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"os"

	"github.com/kovidgoyal/kitty/tools/cli"
)

func run_mime_loop(opts *Options, args []string) (err error) {
	cwd, err = os.Getwd()
	if err != nil {
		return err
	}
	if opts.GetClipboard {
		return run_get_loop(opts, args)
	}
	return run_set_loop(opts, args)
}

func clipboard_main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	if len(args) > 0 {
		return 0, run_mime_loop(opts, args)
	}

	return 0, run_plain_text_loop(opts)
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, clipboard_main)
}
