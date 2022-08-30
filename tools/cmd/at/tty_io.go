// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"os"
	"time"

	"kitty/tools/tui/loop"
)

func do_chunked_io(io_data *rc_io_data) (serialized_response []byte, err error) {
	serialized_response = make([]byte, 0)
	lp, err := loop.New()
	lp.NoAlternateScreen()
	if err != nil {
		return
	}

	var last_received_data_at time.Time
	var final_write_id loop.IdType
	var check_for_timeout func(timer_id loop.IdType) error

	check_for_timeout = func(timer_id loop.IdType) error {
		time_since_last_received_data := time.Now().Sub(last_received_data_at)
		if time_since_last_received_data >= io_data.timeout {
			return os.ErrDeadlineExceeded
		}
		lp.AddTimer(io_data.timeout-time_since_last_received_data, false, check_for_timeout)
		return nil
	}

	transition_to_read := func() {
		if io_data.rc.NoResponse {
			lp.Quit(0)
		}
		last_received_data_at = time.Now()
		lp.AddTimer(io_data.timeout, false, check_for_timeout)
	}

	lp.OnReceivedData = func(data []byte) error {
		last_received_data_at = time.Now()
		return nil
	}

	lp.OnInitialize = func() (string, error) {
		chunk, err := io_data.next_chunk()
		if err != nil {
			return "", err
		}
		write_id := lp.QueueWriteBytesDangerous(chunk)
		if len(chunk) == 0 {
			final_write_id = write_id
		}
		return "", nil
	}

	lp.OnWriteComplete = func(completed_write_id loop.IdType) error {
		if final_write_id > 0 {
			if completed_write_id == final_write_id {
				transition_to_read()
			}
			return nil
		}
		chunk, err := io_data.next_chunk()
		if err != nil {
			return err
		}
		write_id := lp.QueueWriteBytesDangerous(chunk)
		if len(chunk) == 0 {
			final_write_id = write_id
		}
		return nil
	}

	lp.OnRCResponse = func(raw []byte) error {
		serialized_response = raw
		lp.Quit(0)
		return nil
	}

	err = lp.Run()
	if err == nil {
		lp.KillIfSignalled()
	}
	return

}

func do_tty_io(io_data *rc_io_data) (serialized_response []byte, err error) {
	return do_chunked_io(io_data)
}
