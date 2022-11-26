// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"

	"kitty/tools/tty"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
)

var _ = fmt.Print

var _ = fmt.Print

func encode_read_from_clipboard(use_primary bool) string {
	dest := "c"
	if use_primary {
		dest = "p"
	}
	return fmt.Sprintf("\x1b]52;%s;?\x1b\\", dest)
}

type base64_streaming_enc struct {
	output func(string)
}

func (self *base64_streaming_enc) Write(p []byte) (int, error) {
	if len(p) > 0 {
		self.output(string(p))
	}
	return len(p), nil
}

func run_plain_text_loop(opts *Options) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking)
	if err != nil {
		return
	}
	stdin_chan := make(chan string, 1)
	err_chan := make(chan error, 1)
	dest := "c"
	if opts.UsePrimary {
		dest = "p"
	}

	send_to_loop := func(data string) {
		select {
		case stdin_chan <- data:
			lp.WakeupMainThread()
			return
		default:
			lp.WakeupMainThread()
		}
		stdin_chan <- data
	}

	read_from_stdin := func() {
		if !tty.IsTerminal(os.Stdin.Fd()) {
			var buf [8192]byte
			enc := base64.NewEncoder(base64.StdEncoding, &base64_streaming_enc{send_to_loop})
			header_written := false
			for {
				n, err := os.Stdin.Read(buf[:])
				if err != nil {
					if errors.Is(err, io.EOF) {
						enc.Close()
						send_to_loop("\a")
						close(stdin_chan)
						os.Stdin.Close()
						break
					}
					err_chan <- fmt.Errorf("Failed to read from STDIN with error: %w", err)
					lp.WakeupMainThread()
					break
				}
				if n > 0 {
					if !header_written {
						header_written = true
						send_to_loop(fmt.Sprintf("\x1b]52;%s;", dest))
					}
					enc.Write(buf[:n])
				}
			}
		} else {
			close(stdin_chan)
			lp.WakeupMainThread()
		}
	}

	transmitting := true

	lp.OnWakeup = func() error {
		for transmitting {
			select {
			case p, more := <-stdin_chan:
				if more {
					lp.QueueWriteString(p)
				} else {
					transmitting = false
					if opts.GetClipboard {
						lp.QueueWriteString(encode_read_from_clipboard(opts.UsePrimary))
					} else if opts.WaitForCompletion {
						lp.QueueWriteString("\x1bP+q544e\x1b\\")
					} else {
						lp.Quit(0)
					}
				}
			case err := <-err_chan:
				return err
			default:
				return nil
			}
		}
		return nil
	}

	lp.OnInitialize = func() (string, error) {
		go read_from_stdin()
		return "", nil
	}

	var clipboard_contents []byte

	lp.OnEscapeCode = func(etype loop.EscapeCodeType, data []byte) (err error) {
		switch etype {
		case loop.DCS:
			if strings.HasPrefix(utils.UnsafeBytesToString(data), "1+r") {
				lp.Quit(0)
			}
		case loop.OSC:
			q := utils.UnsafeBytesToString(data)
			if strings.HasPrefix(q, "52;") {
				parts := strings.SplitN(q, ";", 3)
				if len(parts) < 3 {
					lp.Quit(0)
					return
				}
				data, err := base64.StdEncoding.DecodeString(parts[2])
				if err != nil {
					return fmt.Errorf("Invalid base64 encoded data from terminal with error: %w", err)
				}
				clipboard_contents = data
				lp.Quit(0)
			}
		}
		return
	}

	esc_count := 0
	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if event.MatchesPressOrRepeat("ctrl+c") || event.MatchesPressOrRepeat("esc") {
			if transmitting {
				return nil
			}
			event.Handled = true
			esc_count++
			if esc_count < 2 {
				key := "esc"
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
	if len(clipboard_contents) > 0 {
		_, err = os.Stdout.Write(clipboard_contents)
		if err != nil {
			err = fmt.Errorf("Failed to write to STDOUT with error: %w", err)
		}
	}
	return
}
