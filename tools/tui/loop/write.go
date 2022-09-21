// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"io"
	"os"
	"time"

	"kitty/tools/tty"
	"kitty/tools/utils"
)

type write_msg struct {
	id    IdType
	bytes []byte
	str   string
}

func (self *write_msg) String() string {
	return fmt.Sprintf("write_msg{%v %#v %#v}", self.id, string(self.bytes), self.str)
}

type write_dispatcher struct {
	str       string
	bytes     []byte
	is_string bool
	is_empty  bool
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

func (self *Loop) flush_pending_writes(tty_write_channel chan<- *write_msg) {
	for len(self.pending_writes) > 0 {
		select {
		case tty_write_channel <- self.pending_writes[0]:
			n := copy(self.pending_writes, self.pending_writes[1:])
			self.pending_writes = self.pending_writes[:n]
		default:
			return
		}
	}
}

func (self *Loop) wait_for_write_to_complete(sentinel IdType, tty_write_channel chan<- *write_msg, write_done_channel <-chan IdType, timeout time.Duration) error {
	for len(self.pending_writes) > 0 {
		select {
		case tty_write_channel <- self.pending_writes[0]:
			self.pending_writes = self.pending_writes[1:]
		case write_id, more := <-write_done_channel:
			if write_id == sentinel {
				return nil
			}
			if self.OnWriteComplete != nil {
				err := self.OnWriteComplete(write_id)
				if err != nil {
					return err
				}
			}
			if !more {
				return fmt.Errorf("The write_done_channel was unexpectedly closed")
			}
		case <-time.After(timeout):
			return os.ErrDeadlineExceeded
		}
	}
	return nil
}

func (self *Loop) add_write_to_pending_queue(data *write_msg) {
	self.pending_writes = append(self.pending_writes, data)
}

func create_write_dispatcher(msg *write_msg) *write_dispatcher {
	self := write_dispatcher{str: msg.str, bytes: msg.bytes, is_string: msg.bytes == nil}
	if self.is_string {
		self.is_empty = self.str == ""
	} else {
		self.is_empty = len(self.bytes) == 0
	}
	return &self
}

func (self *write_dispatcher) write(f *tty.Term) (int, error) {
	if self.is_string {
		return writestring_ignoring_temporary_errors(f, self.str)
	}
	return write_ignoring_temporary_errors(f, self.bytes)
}

func (self *write_dispatcher) slice(n int) {
	if self.is_string {
		self.str = self.str[n:]
		self.is_empty = self.str == ""
	} else {
		self.bytes = self.bytes[n:]
		self.is_empty = len(self.bytes) == 0
	}
}

func write_to_tty(
	pipe_r *os.File, term *tty.Term,
	job_channel <-chan *write_msg, err_channel chan<- error, write_done_channel chan<- IdType,
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
		_, err := selector.WaitForever()
		if err != nil {
			err_channel <- err
			keep_going = false
			return
		}
		if selector.IsReadyToWrite(tty_fd) {
			return
		}
		if selector.IsReadyToRead(pipe_fd) {
			keep_going = false
		}
	}

	write_data := func(msg *write_msg) {
		data := create_write_dispatcher(msg)
		for !data.is_empty {
			wait_for_write_available()
			if !keep_going {
				return
			}
			n, err := data.write(term)
			if err != nil {
				err_channel <- err
				keep_going = false
				return
			}
			if n > 0 {
				data.slice(n)
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

func flush_writer(pipe_w *os.File, tty_write_channel chan<- *write_msg, write_done_channel <-chan IdType, pending_writes []*write_msg, timeout time.Duration) {
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
