package tui

import (
	"fmt"
	"io"
	"kitty/tools/tty"
	"os"
	"time"
)

type TerminalState struct {
	alternate_screen, grab_mouse bool
}

type Loop struct {
	controlling_term *tty.Term
	keep_going       bool
	flush_write_buf  bool
	write_buf        []byte
}

func CreateLoop() (*Loop, error) {
	l := Loop{controlling_term: nil}
	return &l, nil
}

func (self *Loop) Run() (err error) {
	signal_read_file, signal_write_file, err := os.Pipe()
	if err != nil {
		return err
	}
	defer func() {
		signal_read_file.Close()
		signal_write_file.Close()
	}()

	sigchnl := make(chan os.Signal, 256)
	reset_signals := notify_signals(sigchnl, SIGINT, SIGTERM, SIGTSTP, SIGHUP)
	defer reset_signals()

	go func() {
		for {
			s := <-sigchnl
			if write_signal(signal_write_file, s) != nil {
				break
			}
		}
	}()

	controlling_term, err := tty.OpenControllingTerm()
	if err != nil {
		return err
	}
	self.controlling_term = controlling_term
	defer func() {
		self.controlling_term.RestoreAndClose()
		self.controlling_term = nil
	}()
	err = self.controlling_term.ApplyOperations(tty.TCSANOW, tty.SetRaw)
	if err != nil {
		return nil
	}

	var selector Select
	selector.RegisterRead(int(signal_read_file.Fd()))
	selector.RegisterRead(controlling_term.Fd())

	self.keep_going = true
	self.flush_write_buf = true

	defer func() {
		if self.flush_write_buf {
			self.flush()
		}
	}()

	for self.keep_going {
		num_ready, err := selector.WaitForever()
		if err != nil {
			return fmt.Errorf("Failed to call select() with error: %w", err)
		}
		if num_ready == 0 {
			continue
		}
	}

	return nil
}

func (self *Loop) write() error {
	if len(self.write_buf) == 0 || self.controlling_term == nil {
		return nil
	}
	n, err := self.controlling_term.Write(self.write_buf)
	if err != nil {
		return err
	}
	if n == 0 {
		return io.EOF
	}
	remainder := self.write_buf[n:]
	if len(remainder) > 0 {
		self.write_buf = self.write_buf[:len(remainder)]
		copy(self.write_buf, remainder)
	} else {
		self.write_buf = self.write_buf[:0]
	}
	return nil
}

func (self *Loop) flush() error {
	var selector Select
	if self.controlling_term == nil {
		return nil
	}
	selector.RegisterWrite(self.controlling_term.Fd())
	deadline := time.Now().Add(2 * time.Second)
	for len(self.write_buf) > 0 {
		timeout := deadline.Sub(time.Now())
		if timeout < 0 {
			break
		}
		num_ready, err := selector.Wait(timeout)
		if err != nil {
			return err
		}
		if num_ready > 0 && selector.IsReadyToWrite(self.controlling_term.Fd()) {
			err = self.write()
			if err != nil {
				return err
			}
		}
	}
	return nil
}
