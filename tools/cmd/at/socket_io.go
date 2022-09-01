// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"net"
	"time"

	"kitty/tools/utils"
	"kitty/tools/wcswidth"
)

var _ = fmt.Print

func write_all_to_conn(conn *net.Conn, data []byte) error {
	for len(data) > 0 {
		n, err := (*conn).Write(data)
		if err != nil && errors.Is(err, io.ErrShortWrite) {
			err = nil
		}
		if err != nil {
			return err
		}
		data = data[n:]
	}
	return nil
}

func write_many_to_conn(conn *net.Conn, datums ...[]byte) error {
	for len(datums) > 0 {
		err := write_all_to_conn(conn, datums[0])
		if err != nil {
			return err
		}
		datums = datums[1:]
	}
	return nil
}

func read_response_from_conn(conn *net.Conn, timeout time.Duration) (serialized_response []byte, err error) {
	p := wcswidth.EscapeCodeParser{}
	keep_going := true
	p.HandleDCS = func(data []byte) error {
		if bytes.HasPrefix(data, []byte("@kitty-cmd")) {
			serialized_response = data[len("@kitty-cmd"):]
			keep_going = false
		}
		return nil
	}
	buf := make([]byte, utils.DEFAULT_IO_BUFFER_SIZE)
	for keep_going {
		var n int
		(*conn).SetDeadline(time.Now().Add(timeout))
		n, err = (*conn).Read(buf)
		if err != nil {
			keep_going = false
			break
		}
		p.Parse(buf[:n])
	}
	return
}

const cmd_escape_code_prefix = "\x1bP@kitty-cmd"
const cmd_escape_code_suffix = "\x1b\\"

func simple_socket_io(conn *net.Conn, io_data *rc_io_data) (serialized_response []byte, err error) {
	const (
		BEFORE_FIRST_ESCAPE_CODE_SENT = iota
		SENDING
		WAITING_FOR_RESPONSE
	)
	state := BEFORE_FIRST_ESCAPE_CODE_SENT

	wants_streaming := io_data.rc.Stream
	for {
		var chunk []byte
		chunk, err = io_data.next_chunk()
		if err != nil {
			return
		}
		if len(chunk) == 0 {
			state = WAITING_FOR_RESPONSE
			break
		}
		err = write_many_to_conn(conn, []byte(cmd_escape_code_prefix), chunk, []byte(cmd_escape_code_suffix))
		if err != nil {
			return
		}
		if state == BEFORE_FIRST_ESCAPE_CODE_SENT {
			if wants_streaming {
				var streaming_response []byte
				streaming_response, err = read_response_from_conn(conn, io_data.timeout)
				if err != nil {
					return
				}
				if !is_stream_response(streaming_response) {
					err = fmt.Errorf("Did not receive expected streaming response")
					return
				}
			}
			state = SENDING
		}
	}
	if io_data.rc.NoResponse {
		return
	}
	return read_response_from_conn(conn, io_data.timeout)
}

func do_socket_io(io_data *rc_io_data) (serialized_response []byte, err error) {
	conn, err := net.Dial(global_options.to_network, global_options.to_address)
	if err != nil {
		return
	}
	defer conn.Close()
	return simple_socket_io(&conn, io_data)
}
