// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"encoding/json"
	"os"
	"time"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

type stream_response struct {
	Ok     bool `json:"ok"`
	Stream bool `json:"stream"`
}

func is_stream_response(serialized_response []byte) bool {
	var response stream_response
	if len(serialized_response) > 32 {
		return false
	}
	err := json.Unmarshal(serialized_response, &response)
	return err == nil && response.Stream
}

func do_chunked_io(io_data *rc_io_data) (serialized_response []byte, err error) {
	serialized_response = make([]byte, 0)
	// we cant do inbandresize notification as in the --no-response case the
	// command can cause a resize and the loop can quit before the notification
	// arrives, leading to the notification being sent to whatever is executed
	// after us. Similarly no focus tracking.
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors, loop.NoInBandResizeNotifications, loop.NoFocusTracking)
	if io_data.on_key_event != nil {
		lp.FullKeyboardProtocol()
	} else {
		lp.NoKeyboardStateChange()
	}
	if err != nil {
		return
	}

	const (
		BEFORE_FIRST_ESCAPE_CODE_SENT = iota
		WAITING_FOR_STREAMING_RESPONSE
		SENDING
		WAITING_FOR_RESPONSE
	)
	state := BEFORE_FIRST_ESCAPE_CODE_SENT
	var last_received_data_at time.Time
	var check_for_timeout func(timer_id loop.IdType) error
	wants_streaming := false

	check_for_timeout = func(timer_id loop.IdType) (err error) {
		if state != WAITING_FOR_RESPONSE && state != WAITING_FOR_STREAMING_RESPONSE {
			return
		}
		if io_data.on_key_event != nil {
			return
		}
		time_since_last_received_data := time.Since(last_received_data_at)
		if time_since_last_received_data >= io_data.timeout {
			return os.ErrDeadlineExceeded
		}
		_, err = lp.AddTimer(io_data.timeout-time_since_last_received_data, false, check_for_timeout)
		return
	}

	transition_to_read := func() {
		if state == WAITING_FOR_RESPONSE && io_data.rc.NoResponse {
			lp.Quit(0)
		}
		last_received_data_at = time.Now()
		_, _ = lp.AddTimer(io_data.timeout, false, check_for_timeout)
	}

	lp.OnReceivedData = func(data []byte) error {
		last_received_data_at = time.Now()
		return nil
	}

	queue_escape_code := func(data []byte) {
		lp.QueueWriteString(cmd_escape_code_prefix)
		lp.UnsafeQueueWriteBytes(data)
		lp.QueueWriteString(cmd_escape_code_suffix)
	}

	lp.OnInitialize = func() (string, error) {
		chunk, err := io_data.next_chunk()
		wants_streaming = io_data.rc.Stream
		if err != nil {
			if err == waiting_on_stdin {
				return "", nil
			}
			return "", err
		}
		if len(chunk) == 0 {
			state = WAITING_FOR_RESPONSE
			transition_to_read()
		} else {
			queue_escape_code(chunk)
		}
		return "", nil
	}

	lp.OnWriteComplete = func(completed_write_id loop.IdType, has_pending_writes bool) error {
		if state == WAITING_FOR_STREAMING_RESPONSE || state == WAITING_FOR_RESPONSE {
			return nil
		}
		chunk, err := io_data.next_chunk()
		if err != nil {
			if err == waiting_on_stdin {
				return nil
			}
			return err
		}
		if len(chunk) == 0 {
			state = utils.IfElse(state == BEFORE_FIRST_ESCAPE_CODE_SENT && wants_streaming, WAITING_FOR_STREAMING_RESPONSE, WAITING_FOR_RESPONSE)
			transition_to_read()
		} else {
			queue_escape_code(chunk)
		}
		if state == BEFORE_FIRST_ESCAPE_CODE_SENT {
			if wants_streaming {
				state = WAITING_FOR_STREAMING_RESPONSE
				transition_to_read()
			} else {
				state = SENDING
			}
		}
		return nil
	}

	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		if io_data.on_key_event == nil {
			return nil
		}
		err := io_data.on_key_event(lp, event)
		if err == end_reading_from_stdin {
			lp.Quit(0)
			return nil
		}
		if err != nil {
			return err
		}
		chunk, err := io_data.next_chunk()
		if err != nil {
			if err == waiting_on_stdin {
				return nil
			}
			return err
		}
		queue_escape_code(chunk)
		return err
	}

	lp.OnRCResponse = func(raw []byte) error {
		if state == WAITING_FOR_STREAMING_RESPONSE && is_stream_response(raw) {
			state = SENDING
			return lp.OnWriteComplete(0, false)
		}
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
