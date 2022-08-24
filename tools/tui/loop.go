package tui

import (
	"fmt"
	"io"
	"kitty/tools/tty"
	"os"
	"syscall"
	"time"

	"golang.org/x/sys/unix"

	"kitty/tools/utils"
)

func read_ignoring_temporary_errors(fd int, buf []byte) (int, error) {
	n, err := unix.Read(fd, buf)
	if err == unix.EINTR || err == unix.EAGAIN || err == unix.EWOULDBLOCK {
		return 0, nil
	}
	if n == 0 {
		return 0, io.EOF
	}
	return n, err
}

func write_ignoring_temporary_errors(fd int, buf []byte) (int, error) {
	n, err := unix.Write(fd, buf)
	if err == unix.EINTR || err == unix.EAGAIN || err == unix.EWOULDBLOCK {
		return 0, nil
	}
	if n == 0 {
		return 0, io.EOF
	}
	return n, err
}

type Loop struct {
	controlling_term   *tty.Term
	terminal_options   TerminalStateOptions
	escape_code_parser utils.EscapeCodeParser
	keep_going         bool
	flush_write_buf    bool
	death_signal       Signal
	exit_code          int
	write_buf          []byte

	// Callbacks

	// Called when the terminal has been fully setup. Any string returned is sent to
	// the terminal on shutdown
	OnInitialize func(loop *Loop) string

	// Called when a key event happens
	OnKeyEvent func(loop *Loop, event *KeyEvent) error

	// Called when text is received either from a key event or directly from the terminal
	OnText func(loop *Loop, text string, from_key_event bool, in_bracketed_paste bool) error
}

func (self *Loop) handle_csi(raw []byte) error {
	csi := string(raw)
	ke := KeyEventFromCSI(csi)
	if ke != nil {
		return self.handle_key_event(ke)
	}
	return nil
}

func (self *Loop) handle_key_event(ev *KeyEvent) error {
	// self.controlling_term.DebugPrintln(ev)
	if self.OnKeyEvent != nil {
		err := self.OnKeyEvent(self, ev)
		if err != nil {
			return err
		}
		if ev.Handled {
			return nil
		}
	}
	if ev.MatchesPressOrRepeat("ctrl+c") {
		ev.Handled = true
		return self.on_SIGINT()
	}
	if ev.MatchesPressOrRepeat("ctrl+z") {
		ev.Handled = true
		return self.on_SIGTSTP()
	}
	if ev.Text != "" && self.OnText != nil {
		return self.OnText(self, ev.Text, true, false)
	}
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
	if self.OnText != nil {
		return self.OnText(self, string(raw), false, self.escape_code_parser.InBracketedPaste())
	}
	return nil
}

func (self *Loop) on_SIGINT() error {
	self.death_signal = SIGINT
	self.keep_going = false
	return nil
}

func (self *Loop) on_SIGTERM() error {
	self.death_signal = SIGTERM
	self.keep_going = false
	return nil
}

func (self *Loop) on_SIGTSTP() error {
	return nil
}

func (self *Loop) on_SIGHUP() error {
	self.flush_write_buf = false
	self.death_signal = SIGHUP
	self.keep_going = false
	return nil
}

func CreateLoop() (*Loop, error) {
	l := Loop{controlling_term: nil}
	l.terminal_options.alternate_screen = true
	l.escape_code_parser.HandleCSI = l.handle_csi
	l.escape_code_parser.HandleOSC = l.handle_osc
	l.escape_code_parser.HandleDCS = l.handle_dcs
	l.escape_code_parser.HandleAPC = l.handle_apc
	l.escape_code_parser.HandleSOS = l.handle_sos
	l.escape_code_parser.HandlePM = l.handle_pm
	l.escape_code_parser.HandleRune = l.handle_rune
	return &l, nil
}

func (self *Loop) NoAlternateScreen() {
	self.terminal_options.alternate_screen = false
}

func (self *Loop) MouseTracking(mt MouseTracking) {
	self.terminal_options.mouse_tracking = mt
}

func (self *Loop) DeathSignalName() string {
	if self.death_signal != SIGNULL {
		return self.death_signal.String()
	}
	return ""
}

func (self *Loop) KillIfSignalled() {
	switch self.death_signal {
	case SIGINT:
		syscall.Kill(os.Getpid(), syscall.SIGINT)
	case SIGTERM:
		syscall.Kill(os.Getpid(), syscall.SIGTERM)
	case SIGHUP:
		syscall.Kill(os.Getpid(), syscall.SIGHUP)
	}
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

	selector := CreateSelect(8)
	selector.RegisterRead(int(signal_read_file.Fd()))
	selector.RegisterRead(tty_fd)

	self.keep_going = true
	self.flush_write_buf = true
	self.queue_write_to_tty(self.terminal_options.SetStateEscapeCodes())
	finalizer := ""
	if self.OnInitialize != nil {
		finalizer = self.OnInitialize(self)
	}

	defer func() {
		if self.flush_write_buf {
			self.flush()
		}
		self.write_buf = self.write_buf[:0]
		if finalizer != "" {
			self.queue_write_to_tty([]byte(finalizer))
		}
		self.queue_write_to_tty(self.terminal_options.ResetStateEscapeCodes())
		self.flush()
	}()

	read_buf := make([]byte, utils.DEFAULT_IO_BUFFER_SIZE)
	signal_buf := make([]byte, 256)
	self.death_signal = SIGNULL
	self.escape_code_parser.Reset()
	self.exit_code = 0
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
			err = self.write_to_tty()
			if err != nil {
				return err
			}
		}
		if selector.IsReadyToRead(tty_fd) {
			read_buf = read_buf[:cap(read_buf)]
			num_read, err := read_ignoring_temporary_errors(tty_fd, read_buf)
			if err != nil {
				return err
			}
			if num_read > 0 {
				err = self.escape_code_parser.Parse(read_buf[:num_read])
				if err != nil {
					return err
				}
			}
		}
		if selector.IsReadyToRead(int(signal_read_file.Fd())) {
			signal_buf = signal_buf[:cap(signal_buf)]
			err = self.read_signals(signal_read_file, signal_buf)
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

func (self *Loop) QueueWriteString(data string) {
	self.queue_write_to_tty([]byte(data))
}

func (self *Loop) ExitCode() int {
	return self.exit_code
}

func (self *Loop) Beep() {
	self.QueueWriteString("\a")
}

func (self *Loop) Quit(exit_code int) {
	self.exit_code = exit_code
	self.keep_going = false
}

func (self *Loop) write_to_tty() error {
	if len(self.write_buf) == 0 || self.controlling_term == nil {
		return nil
	}
	n, err := write_ignoring_temporary_errors(self.controlling_term.Fd(), self.write_buf)
	if err != nil {
		return err
	}
	if n <= 0 {
		return nil
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
	if self.controlling_term == nil {
		return nil
	}
	selector := CreateSelect(1)
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
