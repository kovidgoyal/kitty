// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"kitty/tools/tui"
	"os"
	"time"
)

func do_chunked_io(io_data *rc_io_data) (serialized_response []byte, err error) {
	serialized_response = make([]byte, 0)
	loop, err := tui.CreateLoop()
	loop.NoAlternateScreen()
	if err != nil {
		return
	}

	var last_received_data_at time.Time
	var check_for_timeout func(loop *tui.Loop, timer_id tui.TimerId) error

	check_for_timeout = func(loop *tui.Loop, timer_id tui.TimerId) error {
		time_since_last_received_data := time.Now().Sub(last_received_data_at)
		if time_since_last_received_data >= io_data.timeout {
			return os.ErrDeadlineExceeded
		}
		loop.AddTimer(io_data.timeout-time_since_last_received_data, false, check_for_timeout)
		return nil
	}

	transition_to_read := func() {
		if io_data.rc.NoResponse {
			loop.Quit(0)
		}
		last_received_data_at = time.Now()
		loop.AddTimer(io_data.timeout, false, check_for_timeout)
	}

	loop.OnReceivedData = func(loop *tui.Loop, data []byte) error {
		last_received_data_at = time.Now()
		return nil
	}

	loop.OnInitialize = func(loop *tui.Loop) (string, error) {
		chunk, err := io_data.next_chunk(true)
		if err != nil {
			return "", err
		}
		if len(chunk) == 0 {
			transition_to_read()
		} else {
			loop.QueueWriteBytes(chunk)
		}
		return "", nil
	}

	loop.OnWriteComplete = func(loop *tui.Loop) error {
		chunk, err := io_data.next_chunk(true)
		if err != nil {
			return err
		}
		if len(chunk) == 0 {
			transition_to_read()
		} else {
			loop.QueueWriteBytes(chunk)
		}
		return nil
	}

	loop.OnRCResponse = func(loop *tui.Loop, raw []byte) error {
		serialized_response = raw
		loop.Quit(0)
		return nil
	}

	err = loop.Run()
	return

}

func do_tty_io(io_data *rc_io_data) (serialized_response []byte, err error) {
	return do_chunked_io(io_data)
}
