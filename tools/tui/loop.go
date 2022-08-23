package tui

import (
	"fmt"
	"io"
	"kitty/tools/tty"
	"os"
	"time"

	"kitty/tools/utils"
)

type Loop struct {
	controlling_term   *tty.Term
	terminal_options   TerminalStateOptions
	escape_code_parser utils.EscapeCodeParser
	keep_going         bool
	flush_write_buf    bool
	write_buf          []byte
}

func (self *Loop) handle_csi(raw []byte) error {
	return nil
}

func (self *Loop) handle_osc(raw []byte) error {
	return nil
}

func (self *Loop) handle_dcs(raw []byte) error {
	return nil
}

func (self *Loop) handle_apc(raw []byte) error {
	return nil
}

func (self *Loop) handle_sos(raw []byte) error {
	return nil
}

func (self *Loop) handle_pm(raw []byte) error {
	return nil
}

func (self *Loop) handle_rune(raw rune) error {
	return nil
}

func CreateLoop() (*Loop, error) {
	l := Loop{controlling_term: nil}
	l.escape_code_parser.HandleCSI = l.handle_csi
	l.escape_code_parser.HandleOSC = l.handle_osc
	l.escape_code_parser.HandleDCS = l.handle_dcs
	l.escape_code_parser.HandleAPC = l.handle_apc
	l.escape_code_parser.HandleSOS = l.handle_sos
	l.escape_code_parser.HandlePM = l.handle_pm
	l.escape_code_parser.HandleRune = l.handle_rune
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
	tty_fd := controlling_term.Fd()
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
	selector.RegisterRead(tty_fd)

	self.keep_going = true
	self.flush_write_buf = true
	self.queue_write_to_tty(self.terminal_options.SetStateEscapeCodes())

	defer func() {
		if self.flush_write_buf {
			self.flush()
		}
		self.write_buf = self.write_buf[:]
		self.queue_write_to_tty(self.terminal_options.ResetStateEscapeCodes())
		self.flush()
	}()

	read_buf := make([]byte, utils.DEFAULT_IO_BUFFER_SIZE)
	self.escape_code_parser.Reset()
	for self.keep_going {
		if len(self.write_buf) > 0 {
			selector.RegisterWrite(tty_fd)
		} else {
			selector.UnRegisterWrite(tty_fd)
		}
		num_ready, err := selector.WaitForever()
		if err != nil {
			return fmt.Errorf("Failed to call select() with error: %w", err)
		}
		if num_ready == 0 {
			continue
		}
		if len(self.write_buf) > 0 && selector.IsReadyToWrite(tty_fd) {
			err := self.write_to_tty()
			if err != nil {
				return err
			}
		}
		if selector.IsReadyToRead(tty_fd) {
			read_buf = read_buf[:cap(read_buf)]
			num_read, err := self.controlling_term.Read(read_buf)
			if err != nil {
				return err
			}
			if num_read == 0 {
				return io.EOF
			}
			err = self.escape_code_parser.Parse(read_buf[:num_read])
			if err != nil {
				return err
			}
		}
	}

	return nil
}

func (self *Loop) queue_write_to_tty(data []byte) {
	self.write_buf = append(self.write_buf, data...)
}

func (self *Loop) write_to_tty() error {
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
			err = self.write_to_tty()
			if err != nil {
				return err
			}
		}
	}
	return nil
}
