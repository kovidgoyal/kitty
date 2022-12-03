// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"kitty/tools/tui/loop"
	"kitty/tools/utils"
)

var _ = fmt.Print

type Input struct {
	src       *os.File
	arg       string
	ext       string
	is_stream bool
	mime_type string
}

func write_loop(inputs []*Input, opts *Options) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return err
	}
	var waiting_for_write loop.IdType
	var buf [4096]byte
	aliases, aerr := parse_aliases(opts.Alias)
	if aerr != nil {
		return aerr
	}

	lp.OnInitialize = func() (string, error) {
		waiting_for_write = lp.QueueWriteString(encode(map[string]string{"type": "write"}, ""))
		return "", nil
	}

	write_chunk := func() error {
		if len(inputs) == 0 {
			return nil
		}
		i := inputs[0]
		n, err := i.src.Read(buf[:])
		if n > 0 {
			waiting_for_write = lp.QueueWriteString(encode_bytes(map[string]string{"type": "wdata", "mime": i.mime_type}, buf[:n]))
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				if len(aliases[i.mime_type]) > 0 {
					lp.QueueWriteString(encode(map[string]string{"type": "walias", "mime": i.mime_type}, strings.Join(aliases[i.mime_type], " ")))
				}
				inputs = inputs[1:]
				if len(inputs) == 0 {
					lp.QueueWriteString(encode(map[string]string{"type": "wdata"}, ""))
					waiting_for_write = 0
				}
				return lp.OnWriteComplete(waiting_for_write)
			}
			return fmt.Errorf("Failed to read from %s with error: %w", i.arg, err)
		}
		return nil
	}

	lp.OnWriteComplete = func(msg_id loop.IdType) error {
		if waiting_for_write == msg_id {
			return write_chunk()
		}
		return nil
	}

	lp.OnEscapeCode = func(etype loop.EscapeCodeType, data []byte) (err error) {
		metadata, _, err := parse_escape_code(etype, data)
		if err != nil {
			return err
		}
		if metadata != nil && metadata["type"] == "write" {
			switch metadata["status"] {
			case "DONE":
				lp.Quit(0)
			case "EIO":
				return fmt.Errorf("Could not write to clipboard an I/O error occurred while the terminal was processing the data")
			case "EINVAL":
				return fmt.Errorf("Could not write to clipboard base64 encoding invalid")
			case "ENOSYS":
				return fmt.Errorf("Could not write to primary selection as the system does not support it")
			case "EPERM":
				return fmt.Errorf("Could not write to clipboard as permission was denied")
			default:
				return fmt.Errorf("Could not write to clipboard unknowns status returned from terminal: %#v", metadata["status"])
			}
		}
		return
	}

	esc_count := 0
	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("ctrl+c") || event.MatchesPressOrRepeat("esc") {
			event.Handled = true
			esc_count++
			if esc_count < 2 {
				key := "Esc"
				if event.MatchesPressOrRepeat("ctrl+c") {
					key = "Ctrl+C"
				}
				lp.QueueWriteString(fmt.Sprintf("Waiting for response from terminal, press %s again to abort. This could cause garbage to be spewed to the screen.\r\n", key))
			} else {
				return fmt.Errorf("Aborted by user!")
			}
		}
		return nil
	}

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

	return
}

func run_set_loop(opts *Options, args []string) (err error) {
	inputs := make([]*Input, len(args))
	to_process := make([]*Input, len(args))
	defer func() {
		for _, i := range inputs {
			if i.src != nil {
				i.src.Close()
			}
		}
	}()

	for i, arg := range args {
		f, err := os.Open(arg)
		if err != nil {
			return fmt.Errorf("Failed to open %s with error: %w", arg, err)
		}
		inputs[i] = &Input{arg: arg, src: f, ext: filepath.Ext(arg), is_stream: arg == "/dev/stdin"}
		if i < len(opts.Mime) {
			inputs[i].mime_type = opts.Mime[i]
		} else if inputs[i].is_stream {
			inputs[i].mime_type = "text/plain"
		} else if inputs[i].ext != "" {
			inputs[i].mime_type = utils.GuessMimeType(inputs[i].arg)
		}
		if inputs[i].mime_type == "" {
			return fmt.Errorf("Could not guess MIME type for %s use the --mime option to specify a MIME type", arg)
		}
		to_process[i] = inputs[i]
	}
	return write_loop(to_process, opts)
}
