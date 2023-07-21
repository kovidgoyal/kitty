// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"fmt"

	"kitty/tools/tui/loop"
)

var _ = fmt.Print

func receive_loop(opts *Options, spec []string, dest string) (err error, rc int) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return err, 1
	}

	err = lp.Run()
	if err != nil {
		return err, 1
	}
	if lp.DeathSignalName() != "" {
		lp.KillIfSignalled()
		return
	}

	if lp.ExitCode() != 0 {
		rc = lp.ExitCode()
	}
	return
}

func receive_main(opts *Options, args []string) (err error, rc int) {
	spec := args
	var dest string
	switch opts.Mode {
	case "mirror":
		if len(args) < 1 {
			return fmt.Errorf("Must specify at least one file to transfer"), 1
		}
	case "normal":
		if len(args) < 2 {
			return fmt.Errorf("Must specify at least one source and a destination file to transfer"), 1
		}
		dest = args[len(args)-1]
		spec = args[:len(args)-1]
	}
	return receive_loop(opts, spec, dest)
}
