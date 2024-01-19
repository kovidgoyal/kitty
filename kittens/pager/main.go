// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package pager

// TODO:
// Scroll to line when starting
// Visual mode elect with copy/paste and copy-on-select
// Mouse based wheel scroll, drag to select, drag scroll, double click to select
// Hyperlinks: Clicking should delegate to terminal and also allow user to specify action
// Keyboard hints mode for clicking hyperlinks
// Display images when used as scrollback pager
// automatic follow when input is a pipe/tty and on last line like tail -f
// syntax highlighting using chroma

import (
	"fmt"

	"kitty/tools/cli"
	"kitty/tools/tty"
)

var _ = fmt.Print
var debugprintln = tty.DebugPrintln
var _ = debugprintln

func main(_ *cli.Command, opts_ *Options, args []string) (rc int, err error) {
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
