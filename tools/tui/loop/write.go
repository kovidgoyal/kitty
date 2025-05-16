// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"io"
	"os"
	"time"

	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils"
)

type write_msg struct {
	id    IdType
	bytes []byte
	str   string
}

func (self *write_msg) String() string {
	return fmt.Sprintf("write_msg{%v %#v %#v}", self.id, string(self.bytes), self.str)
}

func write_ignoring_temporary_errors(f *tty.Term, buf []byte) (int, error) {
	n, err := f.Write(buf)
	if err != nil {
		if is_temporary_error(err) {
			err = nil
		}
		return n, err
	}
	if n == 0 {
		return 0, io.EOF
	}
	return n, err
}

func writestring_ignoring_temporary_errors(f *tty.Term, buf string) (int, error) {
	n, err := f.WriteString(buf)
	if err != nil {
		if is_temporary_error(err) {
			err = nil
		}
		return n, err
	}
	if n == 0 {
		return 0, io.EOF
	}
	return n, err
}

func (self *Loop) flush_pending_writes(tty_write_channel chan<- write_msg) (num_sent int) {
	defer func() {
		if num_sent > 0 {
			self.pending_writes = utils.ShiftLeft(self.pending_writes, num_sent)
		}
	}()
	for len(self.pending_writes) > num_sent {
		select {
		case tty_write_channel <- self.pending_writes[num_sent]:
			num_sent++
		default:
			return
		}
	}
	return
}

func (self *Loop) wait_for_write_to_complete(sentinel IdType, tty_write_channel chan<- write_msg, write_done_channel <-chan IdType, timeout time.Duration) error {
	num_sent := 0
	defer func() {
		if num_sent > 0 {
			self.pending_writes = utils.ShiftLeft(self.pending_writes, num_sent)
		}
	}()

	end_time := time.Now().Add(timeout)
	for num_sent < len(self.pending_writes) {
		timeout = time.Until(end_time)
		if timeout <= 0 {
			return os.ErrDeadlineExceeded
		}
		select {
		case tty_write_channel <- self.pending_writes[num_sent]:
			num_sent++
		case write_id, more := <-write_done_channel:
			if self.OnWriteComplete != nil {
				err := self.OnWriteComplete(write_id, write_id < self.write_msg_id_counter)
				if err != nil {
					return err
				}
			}
			if write_id == sentinel {
				return nil
			}
			if !more {
				return fmt.Errorf("The write_done_channel was unexpectedly closed")
			}
		case <-time.After(timeout):
			return os.ErrDeadlineExceeded
		}
	}
	for {
		timeout = time.Until(end_time)
		if timeout <= 0 {
			return os.ErrDeadlineExceeded
		}
		select {
		case write_id, more := <-write_done_channel:
			if self.OnWriteComplete != nil {
				err := self.OnWriteComplete(write_id, write_id < self.write_msg_id_counter)
				if err != nil {
					return err
				}
			}
			if write_id == sentinel {
				return nil
			}
			if !more {
				return fmt.Errorf("The write_done_channel was unexpectedly closed")
			}
		case <-time.After(timeout):
			return os.ErrDeadlineExceeded
		}
	}
}

func (self *Loop) add_write_to_pending_queue(data write_msg) {
	if len(self.pending_writes) > 0 || self.tty_write_channel == nil {
		self.pending_writes = append(self.pending_writes, data)
	} else {
		select {
		case self.tty_write_channel <- data:
		default:
			self.pending_writes = append(self.pending_writes, data)
		}
	}
}

func (self write_msg) is_empty() bool {
	if self.bytes == nil {
		return self.str == ""
	}
	return len(self.bytes) == 0
}

func (self *write_msg) write(f *tty.Term) (err error) {
	n := 0
	if self.bytes == nil {
		n, err = writestring_ignoring_temporary_errors(f, self.str)
	} else {
		n, err = write_ignoring_temporary_errors(f, self.bytes)
	}
	if n > 0 {
		if self.bytes == nil {
			self.str = self.str[n:]
		} else {
			self.bytes = self.bytes[n:]
		}
	}
	return
}

func write_to_tty(
	pipe_r *os.File, term *tty.Term,
	job_channel <-chan write_msg, err_channel chan<- error, write_done_channel chan<- IdType,
) {
	keep_going := true
	defer func() {
		pipe_r.Close()
		close(write_done_channel)
	}()
	selector := utils.CreateSelect(2)
	pipe_fd := int(pipe_r.Fd())
	tty_fd := term.Fd()
	selector.RegisterRead(pipe_fd)
	selector.RegisterWrite(tty_fd)

	wait_for_write_available := func() {
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

	write_data := func(msg write_msg) {
		for !msg.is_empty() {
			wait_for_write_available()
			if !keep_going {
				return
			}
			if err := msg.write(term); err != nil {
				err_channel <- err
				keep_going = false
				return
			}
		}
	}

	for {
		data, more := <-job_channel
		if !more {
			keep_going = false
			break
		}
		write_data(data)
		if keep_going {
			write_done_channel <- data.id
		} else {
			break
		}
	}
}

func flush_writer(pipe_w *os.File, tty_write_channel chan<- write_msg, write_done_channel <-chan IdType, pending_writes []write_msg, timeout time.Duration) {
	writer_quit := false
	defer func() {
		if tty_write_channel != nil {
			close(tty_write_channel)
			tty_write_channel = nil
		}
		pipe_w.Close()
		if !writer_quit {
			for {
				_, more := <-write_done_channel
				if !more {
					writer_quit = true
					break
				}
			}
		}
	}()
	deadline := time.Now().Add(timeout)
	for len(pending_writes) > 0 && !writer_quit {
		timeout = time.Until(deadline)
		if timeout <= 0 {
			return
		}
		select {
		case <-time.After(timeout):
			return
		case _, more := <-write_done_channel:
			if !more {
				writer_quit = true
			}
		case tty_write_channel <- pending_writes[0]:
			pending_writes = pending_writes[1:]
		}
	}
	close(tty_write_channel)
	tty_write_channel = nil
	timeout = time.Until(deadline)
	if timeout <= 0 {
		return
	}
	for !writer_quit {
		select {
		case _, more := <-write_done_channel:
			if !more {
				writer_quit = true
			}
		case <-time.After(timeout):
			return
		}
	}
}
