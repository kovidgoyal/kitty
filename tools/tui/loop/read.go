// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"
	"time"

	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

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
	if is_temporary_error(err) {
		return 0, nil
	}
	if n == 0 {
		return 0, io.EOF
	}
	return n, err
}

func read_from_tty(pipe_r *os.File, term *tty.Term, results_channel chan<- []byte, err_channel chan<- error, quit_channel <-chan byte, leftover_channel chan<- []byte) {
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
		for {
			n, err := selector.WaitForever()
			if err != nil && err != unix.EINTR {
				err_channel <- err
				keep_going = false
				return
			}
			if n > 0 {
				break
			}
		}
		if selector.IsReadyToRead(pipe_fd) {
			keep_going = false
		}
	}

	buf := make([]byte, bufsize)
	for keep_going {
		if len(buf) < 64 {
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
		if n == 0 { // temporary error
			continue
		}
		send := buf[:n]
		buf = buf[n:]
		select {
		case results_channel <- send:
		case <-quit_channel:
			leftover_channel <- send
			keep_going = false
		}
	}
}

func has_da1_response(s string) bool {
	pat := regexp.MustCompile("\x1b\\[\\?[0-9:;]+c")
	return pat.FindString(s) != ""
}

func read_until_primary_device_attributes_response(term *tty.Term, initial_bytes []byte, timeout time.Duration) {
	s := strings.Builder{}
	if initial_bytes != nil {
		s.Write(initial_bytes)
	}
	received := make(chan error)
	go func() {
		buf := make([]byte, 1024)
		n, err := read_ignoring_temporary_errors(term, buf)
		if n > 0 {
			s.Write(buf[:n])
			if has_da1_response(s.String()) {
				received <- nil
				return
			}
		}
		if err != nil {
			received <- err
		}
	}()
	select {
	case <-received:
	case <-time.After(timeout):
	}
}
