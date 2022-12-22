// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"errors"
	"fmt"
	"os"

	"kitty/tools/cli"
	"kitty/tools/tty"
	"kitty/tools/tui/graphics"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"kitty/tools/utils/shm"
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
var shm_files_to_delete []shm.MMap
var direct_query_id, file_query_id, memory_query_id uint32
var stderr_is_tty bool
var query_in_flight bool
var stream_response string

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
	query_in_flight = true
	g := func(t graphics.GRT_t, payload string) uint32 {
		iid += 1
		g1 := &graphics.GraphicsCommand{}
		g1.SetTransmission(t).SetAction(graphics.GRT_action_query).SetImageId(iid).SetDataWidth(1).SetDataHeight(1).SetFormat(
			graphics.GRT_format_rgb).SetDataSize(uint64(len(payload)))
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
	sf, err := shm.CreateTemp("icat-", 3)
	if err == nil {
		memory_query_id = g(graphics.GRT_transmission_sharedmem, sf.Name())
		shm_files_to_delete = append(shm_files_to_delete, sf)
		copy(sf.Slice(), []byte{1, 2, 3})
		sf.Close()
	} else {
		transfer_by_memory = unsupported
		var ens *shm.ErrNotSupported
		if !errors.As(err, &ens) {
			print_error("Failed to create SHM for data transfer, memory based transfer is disabled. Error: %v", err)
		}
	}
	lp.QueueWriteString("\x1b[c")

	return "", nil
}

func on_query_finished() (err error) {
	query_in_flight = false
	if transfer_by_stream != supported {
		return fmt.Errorf("This terminal emulator does not support the graphics protocol, use a terminal emulator such as kitty that does support it")
	}
	if opts.DetectSupport {
		switch {
		case transfer_by_memory == supported:
			print_error("memory")
		case transfer_by_file == supported:
			print_error("file")
		default:
			print_error("stream")
		}
		lp.Quit(0)
		return
	}
	return
}

func on_query_response(g *graphics.GraphicsCommand) (err error) {
	var tm *transfer_mode
	switch g.ImageId() {
	case direct_query_id:
		tm = &transfer_by_stream
	case file_query_id:
		tm = &transfer_by_file
	case memory_query_id:
		tm = &transfer_by_memory
	}
	if g.ResponseMessage() == "OK" {
		*tm = supported
	} else {
		*tm = unsupported
	}
	return
}

func on_escape_code(etype loop.EscapeCodeType, payload []byte) (err error) {
	switch etype {
	case loop.CSI:
		if len(payload) > 3 && payload[0] == '?' && payload[len(payload)-1] == 'c' {
			return on_query_finished()
		}
	case loop.APC:
		g := graphics.GraphicsCommandFromAPC(payload)
		if g != nil {
			if query_in_flight {
				return on_query_response(g)
			}
		}
	}
	return
}

func on_finalize() string {
	if len(temp_files_to_delete) > 0 && transfer_by_file != supported {
		for _, name := range temp_files_to_delete {
			os.Remove(name)
		}
	}
	if len(shm_files_to_delete) > 0 && transfer_by_memory != supported {
		for _, name := range shm_files_to_delete {
			name.Unlink()
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
	shm_files_to_delete = make([]shm.MMap, 0, 8)
	lp, err = loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return
	}
	lp.OnInitialize = on_initialize
	lp.OnFinalize = on_finalize
	lp.OnEscapeCode = on_escape_code

	err = lp.Run()
	if err != nil {
		return
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return
	}
	return 0, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
