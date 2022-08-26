// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"io"
	"os"

	"golang.org/x/sys/unix"

	"kitty/tools/tty"
	"kitty/tools/utils"
)

func (self *Loop) dispatch_input_data(data []byte) error {
	if self.OnReceivedData != nil {
		err := self.OnReceivedData(data)
		if err != nil {
			return err
		}
	}
	err := self.escape_code_parser.Parse(data)
	if err != nil {
		return err
	}
	return nil
}

func read_ignoring_temporary_errors(f *tty.Term, buf []byte) (int, error) {
	n, err := f.Read(buf)
	if err == unix.EINTR || err == unix.EAGAIN || err == unix.EWOULDBLOCK {
		return 0, nil
	}
	if n == 0 {
		return 0, io.EOF
	}
	return n, err
}

func read_from_tty(pipe_r *os.File, term *tty.Term, results_channel chan<- []byte, err_channel chan<- error, quit_channel <-chan byte) {
	keep_going := true
	pipe_fd := int(pipe_r.Fd())
	tty_fd := term.Fd()
	selector := utils.CreateSelect(2)
	selector.RegisterRead(pipe_fd)
	selector.RegisterRead(tty_fd)

	defer func() {
		close(results_channel)
		pipe_r.Close()
	}()

	const bufsize = 2 * utils.DEFAULT_IO_BUFFER_SIZE

	wait_for_read_available := func() {
		_, err := selector.WaitForever()
		if err != nil {
			err_channel <- err
			keep_going = false
			return
		}
		if selector.IsReadyToRead(pipe_fd) {
			keep_going = false
			return
		}
		if selector.IsReadyToRead(tty_fd) {
			return
		}
	}

	buf := make([]byte, bufsize)
	for keep_going {
		if len(buf) == 0 {
			buf = make([]byte, bufsize)
		}
		if wait_for_read_available(); !keep_going {
			break
		}
		n, err := read_ignoring_temporary_errors(term, buf)
		if err != nil {
			err_channel <- err
			keep_going = false
			break
		}
		if n == 0 {
			err_channel <- io.EOF
			keep_going = false
			break
		}
		send := buf[:n]
		buf = buf[n:]
		select {
		case results_channel <- send:
		case <-quit_channel:
			keep_going = false
			break
		}
	}
}
