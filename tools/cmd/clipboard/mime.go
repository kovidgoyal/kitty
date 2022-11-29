// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"strings"

	"kitty/tools/tui/loop"
	"kitty/tools/utils"
)

var _ = fmt.Print

const OSC_NUMBER = "5522"

func run_get_loop(opts *Options, args []string) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return
	}
	var available_mimes []string
	reading_available_mimes := true

	lp.OnInitialize = func() (string, error) {
		lp.QueueWriteString("\x1b]" + OSC_NUMBER + ";type=read;.\x1b\\")
		return "", nil
	}

	lp.OnEscapeCode = func(etype loop.EscapeCodeType, data []byte) (err error) {
		if etype != loop.OSC || !bytes.HasPrefix(data, utils.UnsafeStringToBytes(OSC_NUMBER+";")) {
			return
		}
		parts := bytes.SplitN(data, utils.UnsafeStringToBytes(";"), 3)
		metadata := make(map[string]string)
		var payload []byte
		if len(parts) > 2 && len(parts[2]) > 0 {
			payload, err = base64.StdEncoding.DecodeString(utils.UnsafeBytesToString(parts[2]))
			if err != nil {
				err = fmt.Errorf("Received OSC %s packet from terminal with invalid base64 encoded payload", OSC_NUMBER)
				return
			}
		}
		if len(parts) > 1 {
			for _, record := range bytes.Split(parts[1], utils.UnsafeStringToBytes(":")) {
				rp := bytes.SplitN(record, utils.UnsafeStringToBytes("="), 2)
				v := ""
				if len(rp) == 2 {
					v = string(rp[1])
				}
				metadata[string(rp[0])] = v
			}
		}
		if reading_available_mimes {
			switch metadata["status"] {
			case "DATA":
				available_mimes = strings.Split(utils.UnsafeBytesToString(payload), " ")
			case "OK":
			case "DONE":
				reading_available_mimes = false
				if len(available_mimes) == 0 {
					return fmt.Errorf("The clipboard is empty")
				}
				return fmt.Errorf("TODO: Implement processing available mimes")
			default:
				return fmt.Errorf("Failed to read list of available data types in the clipboard with error: %s", metadata["status"])
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
	return fmt.Errorf("TODO: Implement me")
}

func run_mime_loop(opts *Options, args []string) error {
	if opts.GetClipboard {
		return run_get_loop(opts, args)
	}
	return run_set_loop(opts, args)
}
