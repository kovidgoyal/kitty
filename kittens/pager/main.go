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
	"os"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
)

var _ = fmt.Print
var debugprintln = tty.DebugPrintln
var _ = debugprintln

type input_line_struct struct {
	line                 string
	num_carriage_returns int
	is_a_complete_line   bool
	err                  error
}

type global_state_struct struct {
	input_file_name string
	opts            *Options
}

var global_state global_state_struct

func main(_ *cli.Command, opts_ *Options, args []string) (rc int, err error) {
	global_state.opts = opts_
	input_channel := make(chan input_line_struct, 4096)
	var input_file *os.File
	if len(args) > 1 {
		return 1, fmt.Errorf("Only a single file can be viewed at a time")
	}
	if len(args) == 0 {
		if tty.IsTerminal(os.Stdin.Fd()) {
			return 1, fmt.Errorf("STDIN is a terminal and no filename specified. See --help")
		}
		input_file = os.Stdin
		global_state.input_file_name = "/dev/stdin"
	} else {
		input_file, err = os.Open(args[0])
		if err != nil {
			return 1, err
		}
		if tty.IsTerminal(input_file.Fd()) {
			return 1, fmt.Errorf("%s is a terminal not paging it", args[0])
		}
		global_state.input_file_name = args[0]
	}
	follow := global_state.opts.Follow
	if follow && global_state.input_file_name == "/dev/stdin" {
		follow = false
	}
	go read_input(input_file, global_state.input_file_name, input_channel, follow, global_state.opts.Role == "scrollback")
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
