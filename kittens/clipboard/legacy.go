// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"bytes"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
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
	output          func(string) loop.IdType
	last_written_id loop.IdType
}

func (self *base64_streaming_enc) Write(p []byte) (int, error) {
	if len(p) > 0 {
		self.last_written_id = self.output(string(p))
	}
	return len(p), nil
}

var ErrTooMuchPipedData = errors.New("Too much piped data")

func read_all_with_max_size(r io.Reader, max_size int) ([]byte, error) {
	b := make([]byte, 0, utils.Min(8192, max_size))
	for {
		if len(b) == cap(b) {
			new_size := utils.Min(2*cap(b), max_size)
			if new_size <= cap(b) {
				return b, ErrTooMuchPipedData
			}
			b = append(make([]byte, 0, new_size), b...)
		}
		n, err := r.Read(b[len(b):cap(b)])
		b = b[:len(b)+n]
		if err != nil {
			if err == io.EOF {
				err = nil
			}
			return b, err
		}
	}
}

func preread_stdin() (data_src io.Reader, tempfile *os.File, err error) {
	// we pre-read STDIN because otherwise if the output of a command is being piped in
	// and that command itself transmits on the tty we will break. For example
	// kitten @ ls | kitten clipboard
	var stdin_data []byte
	stdin_data, err = read_all_with_max_size(os.Stdin, 2*1024*1024)
	if err == nil {
		os.Stdin.Close()
	} else if err != ErrTooMuchPipedData {
		os.Stdin.Close()
		err = fmt.Errorf("Failed to read from STDIN pipe with error: %w", err)
		return
	}
	if err == ErrTooMuchPipedData {
		tempfile, err = utils.CreateAnonymousTemp("")
		if err != nil {
			return nil, nil, fmt.Errorf("Failed to create a temporary from STDIN pipe with error: %w", err)
		}
		tempfile.Write(stdin_data)
		_, err = io.Copy(tempfile, os.Stdin)
		os.Stdin.Close()
		if err != nil {
			return nil, nil, fmt.Errorf("Failed to copy data from STDIN pipe to temp file with error: %w", err)
		}
		tempfile.Seek(0, io.SeekStart)
		data_src = tempfile
	} else if stdin_data != nil {
		data_src = bytes.NewBuffer(stdin_data)
	}
	return
}

func run_plain_text_loop(opts *Options) (err error) {
	stdin_is_tty := tty.IsTerminal(os.Stdin.Fd())
	var data_src io.Reader
	var tempfile *os.File
	if !stdin_is_tty && !opts.GetClipboard {
		// we dont read STDIN when getting clipboard as it makes it hard to use the kitten in contexts where
		// the user does not control STDIN such as being execed from other programs.
		data_src, tempfile, err = preread_stdin()
		if err != nil {
			return err
		}
		if tempfile != nil {
			defer tempfile.Close()
		}
	}
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoMouseTracking, loop.NoInBandResizeNotifications)
	if err != nil {
		return
	}
	dest := "c"
	if opts.UsePrimary {
		dest = "p"
	}

	send_to_loop := func(data string) loop.IdType {
		return lp.QueueWriteString(data)
	}
	enc_writer := base64_streaming_enc{output: send_to_loop}
	enc := base64.NewEncoder(base64.StdEncoding, &enc_writer)
	transmitting := true

	after_read_from_stdin := func() {
		transmitting = false
		if opts.GetClipboard {
			lp.QueueWriteString(encode_read_from_clipboard(opts.UsePrimary))
		} else if opts.WaitForCompletion {
			lp.QueueWriteString("\x1bP+q544e\x1b\\")
		} else {
			lp.Quit(0)
		}
	}

	buf := make([]byte, 8192)
	write_one_chunk := func() error {
		orig := enc_writer.last_written_id
		for enc_writer.last_written_id == orig {
			n, err := data_src.Read(buf[:cap(buf)])
			if n > 0 {
				enc.Write(buf[:n])
			}
			if err == nil {
				continue
			}
			if errors.Is(err, io.EOF) {
				enc.Close()
				send_to_loop("\x1b\\")
				after_read_from_stdin()
				return nil
			}
			send_to_loop("\x1b\\")
			return err
		}
		return nil
	}

	lp.OnInitialize = func() (string, error) {
		if data_src != nil {
			send_to_loop(fmt.Sprintf("\x1b]52;%s;", dest))
			return "", write_one_chunk()
		}
		after_read_from_stdin()
		return "", nil
	}

	lp.OnWriteComplete = func(id loop.IdType, has_pending_writes bool) error {
		if id == enc_writer.last_written_id {
			return write_one_chunk()
		}
		return nil
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
	if len(clipboard_contents) > 0 {
		_, err = os.Stdout.Write(clipboard_contents)
		if err != nil {
			err = fmt.Errorf("Failed to write to STDOUT with error: %w", err)
		}
	}
	return
}
