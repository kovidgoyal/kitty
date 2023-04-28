// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"fmt"
)

var _ = fmt.Print

func send_main(opts *Options, args []string) (err error) {
	fmt.Println("Scanning files…")
	files := files_for_send(opts, args)
	fmt.Printf("Found %d files and directories, requesting transfer permission…", len(files))
	fmt.Println()

	return
}
