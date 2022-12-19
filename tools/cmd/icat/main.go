// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"fmt"
	"os"

	"kitty/tools/cli"
	"kitty/tools/tty"
	"kitty/tools/tui/graphics"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
)

var _ = fmt.Print

var opts *Options
var lp *loop.Loop

type transfer_mode int

const (
	unknown transfer_mode = iota
	unsupported
	supported
)

var transfer_by_file, transfer_by_memory, transfer_by_stream transfer_mode

var temp_files_to_delete []string
var direct_query_id, file_query_id, memory_query_id uint32
var stderr_is_tty bool

func print_error(format string, args ...any) {
	if lp == nil || !stderr_is_tty {
		fmt.Fprintf(os.Stderr, format, args...)
		fmt.Fprintln(os.Stderr)
	} else {
		lp.QueueWriteString(fmt.Sprintf(format, args...))
		lp.QueueWriteString("\r\n")
	}
}

func on_initialize() (string, error) {
	var iid uint32
	g := func(t graphics.GRT_t, payload string) uint32 {
		iid += 1
		g1 := &graphics.GraphicsCommand{}
		g1.SetTransmission(t).SetAction(graphics.GRT_action_query).SetImageId(iid).SetDataWidth(1).SetDataHeight(1).SetFormat(graphics.GRT_format_rgb)
		g1.WriteWithPayloadToLoop(lp, utils.UnsafeStringToBytes(payload))
		return iid
	}
	sz, err := lp.ScreenSize()
	if err != nil {
		return "", fmt.Errorf("Failed to query terminal for screen size with error: %w", err)
	}
	if sz.WidthPx == 0 || sz.HeightPx == 0 {
		return "", fmt.Errorf("Terminal does not support reporting screen sizes via the TIOCGWINSZ ioctl")
	}
	direct_query_id = g(graphics.GRT_transmission_direct, "123")
	tf, err := graphics.MakeTemp()
	if err == nil {
		file_query_id = g(graphics.GRT_transmission_tempfile, tf.Name())
		temp_files_to_delete = append(temp_files_to_delete, tf.Name())
		tf.Write([]byte{1, 2, 3})
		tf.Close()
	} else {
		transfer_by_file = unsupported
		print_error("Failed to create temporary file for data transfer, file based transfer is disabled. Error: %v", err)
	}

	return "", nil
}

func on_finalize() string {
	if len(temp_files_to_delete) > 0 {
		for _, name := range temp_files_to_delete {
			os.Remove(name)
		}
	}
	return ""
}

func main(cmd *cli.Command, o *Options, args []string) (rc int, err error) {
	opts = o
	stderr_is_tty = tty.IsTerminal(os.Stderr.Fd())
	if opts.PrintWindowSize {
		t, err := tty.OpenControllingTerm()
		if err != nil {
			return 1, fmt.Errorf("Failed to open controlling terminal with error: %w", err)
		}
		sz, err := t.GetSize()
		if err != nil {
			return 1, fmt.Errorf("Failed to query terminal using TIOCGWINSZ with error: %w", err)
		}
		fmt.Printf("%dx%d", sz.Xpixel, sz.Ypixel)
		return 0, nil
	}
	temp_files_to_delete = make([]string, 0, 8)
	lp, err = loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return
	}
	lp.OnInitialize = on_initialize
	lp.OnFinalize = on_finalize

	return 0, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
