// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"strconv"
	"time"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
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

type response_reader struct {
	parser            wcswidth.EscapeCodeParser
	storage           [utils.DEFAULT_IO_BUFFER_SIZE]byte
	pending_responses [][]byte
}

func (r *response_reader) read_response_from_conn(conn *net.Conn, timeout time.Duration) (serialized_response []byte, err error) {
	keep_going := true
	if len(r.pending_responses) == 0 {
		r.parser.HandleDCS = func(data []byte) error {
			if bytes.HasPrefix(data, []byte("@kitty-cmd")) {
				r.pending_responses = append(r.pending_responses, append([]byte{}, data[len("@kitty-cmd"):]...))
				keep_going = false
			}
			return nil
		}
		buf := r.storage[:]
		for keep_going {
			var n int
			(*conn).SetDeadline(time.Now().Add(timeout))
			n, err = (*conn).Read(buf)
			if err != nil {
				keep_going = false
				break
			}
			r.parser.Parse(buf[:n])
		}
	}
	if len(r.pending_responses) > 0 {
		serialized_response = r.pending_responses[0]
		r.pending_responses = r.pending_responses[1:]
	}
	return
}

const cmd_escape_code_prefix = "\x1bP@kitty-cmd"
const cmd_escape_code_suffix = "\x1b\\"

func run_stdin_echo_loop(conn *net.Conn, io_data *rc_io_data) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return
	}
	lp.OnKeyEvent = func(event *loop.KeyEvent) error {
		event.Handled = true
		err = io_data.on_key_event(lp, event)
		if err != nil {
			if err == end_reading_from_stdin {
				lp.Quit(0)
				return nil
			}
			return err
		}
		chunk, err := io_data.next_chunk()
		if err != nil {
			if err == waiting_on_stdin {
				return nil
			}
			return err
		}
		err = write_many_to_conn(conn, []byte(cmd_escape_code_prefix), chunk, []byte(cmd_escape_code_suffix))
		if err != nil {
			return err
		}
		return nil
	}
	err = lp.Run()
	if err == nil {
		lp.KillIfSignalled()
	}
	return err
}

func simple_socket_io(conn *net.Conn, io_data *rc_io_data) (serialized_response []byte, err error) {
	r := response_reader{}
	r.pending_responses = make([][]byte, 0, 2) // we read at most two responses
	first_escape_code_sent := false
	wants_streaming := io_data.rc.Stream
	for {
		var chunk []byte
		chunk, err = io_data.next_chunk()
		if err != nil {
			if err == waiting_on_stdin {
				err := run_stdin_echo_loop(conn, io_data)
				return make([]byte, 0), err
			}
			return
		}
		if len(chunk) == 0 {
			break
		}
		err = write_many_to_conn(conn, []byte(cmd_escape_code_prefix), chunk, []byte(cmd_escape_code_suffix))
		if err != nil {
			return
		}
		if !first_escape_code_sent {
			first_escape_code_sent = true
			if wants_streaming {
				var streaming_response []byte
				streaming_response, err = r.read_response_from_conn(conn, io_data.timeout)
				if err != nil {
					return
				}
				if !is_stream_response(streaming_response) {
					err = fmt.Errorf("Did not receive expected streaming response")
					return
				}
			}
		}
	}
	if io_data.rc.NoResponse {
		return
	}
	return r.read_response_from_conn(conn, io_data.timeout)
}

func do_socket_io(io_data *rc_io_data) (serialized_response []byte, err error) {
	var conn net.Conn
	if global_options.to_network == "fd" {
		fd, _ := strconv.Atoi(global_options.to_address)
		if err != nil {
			return nil, err
		}
		f := os.NewFile(uintptr(fd), "fd:"+global_options.to_address)
		conn, err = net.FileConn(f)
		if err != nil {
			return nil, fmt.Errorf("Failed to open a socket for the remote control file descriptor: %d with error: %w", fd, err)
		}
		defer f.Close()
	} else {
		network := utils.IfElse(global_options.to_network == "ip", "tcp", global_options.to_network)
		conn, err = net.Dial(network, global_options.to_address)
		if err != nil {
			err = fmt.Errorf("Failed to connect to %s:%s with error: %w", network, global_options.to_address, err)
			return
		}
	}
	defer conn.Close()
	return simple_socket_io(&conn, io_data)
}
