// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"runtime/debug"
	"time"

	"golang.org/x/sys/unix"

	"kitty/tools/tty"
	"kitty/tools/utils"
)

var SIGNULL unix.Signal

func new_loop() *Loop {
	l := Loop{controlling_term: nil, timers_temp: make([]*timer, 4)}
	l.terminal_options.alternate_screen = true
	l.terminal_options.restore_colors = true
	l.terminal_options.kitty_keyboard_mode = 0b11111
	l.escape_code_parser.HandleCSI = l.handle_csi
	l.escape_code_parser.HandleOSC = l.handle_osc
	l.escape_code_parser.HandleDCS = l.handle_dcs
	l.escape_code_parser.HandleAPC = l.handle_apc
	l.escape_code_parser.HandleSOS = l.handle_sos
	l.escape_code_parser.HandlePM = l.handle_pm
	l.escape_code_parser.HandleRune = l.handle_rune
	l.escape_code_parser.HandleEndOfBracketedPaste = l.handle_end_of_bracketed_paste
	return &l
}

func is_temporary_error(err error) bool {
	return errors.Is(err, unix.EINTR) || errors.Is(err, unix.EAGAIN) || errors.Is(err, unix.EWOULDBLOCK) || errors.Is(err, io.ErrShortWrite)
}

func kill_self(sig unix.Signal) {
	unix.Kill(os.Getpid(), sig)
	// Give the signal time to be delivered
	time.Sleep(20 * time.Millisecond)
}

func (self *Loop) print_stack() {
	self.DebugPrintln(string(debug.Stack()))
}

func (self *Loop) update_screen_size() error {
	if self.controlling_term == nil {
		return fmt.Errorf("No controlling terminal cannot update screen size")
	}
	ws, err := self.controlling_term.GetSize()
	if err != nil {
		return err
	}
	s := &self.screen_size
	s.updated = true
	s.HeightCells, s.WidthCells = uint(ws.Row), uint(ws.Col)
	s.HeightPx, s.WidthPx = uint(ws.Ypixel), uint(ws.Xpixel)
	s.CellWidth = s.WidthPx / s.WidthCells
	s.CellHeight = s.HeightPx / s.HeightCells
	return nil
}

func (self *Loop) handle_csi(raw []byte) error {
	csi := string(raw)
	ke := KeyEventFromCSI(csi)
	if ke != nil {
		return self.handle_key_event(ke)
	}
	if self.OnEscapeCode != nil {
		return self.OnEscapeCode(CSI, raw)
	}
	return nil
}

func (self *Loop) handle_key_event(ev *KeyEvent) error {
	if self.OnKeyEvent != nil {
		err := self.OnKeyEvent(ev)
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
		return self.OnText(ev.Text, true, false)
	}
	return nil
}

func (self *Loop) handle_osc(raw []byte) error {
	if self.OnEscapeCode != nil {
		return self.OnEscapeCode(OSC, raw)
	}
	return nil
}

func (self *Loop) handle_dcs(raw []byte) error {
	if self.OnRCResponse != nil && bytes.HasPrefix(raw, utils.UnsafeStringToBytes("@kitty-cmd")) {
		return self.OnRCResponse(raw[len("@kitty-cmd"):])
	}
	if self.OnEscapeCode != nil {
		return self.OnEscapeCode(DCS, raw)
	}
	return nil
}

func (self *Loop) handle_apc(raw []byte) error {
	if self.OnEscapeCode != nil {
		return self.OnEscapeCode(APC, raw)
	}
	return nil
}

func (self *Loop) handle_sos(raw []byte) error {
	if self.OnEscapeCode != nil {
		return self.OnEscapeCode(SOS, raw)
	}
	return nil
}

func (self *Loop) handle_pm(raw []byte) error {
	if self.OnEscapeCode != nil {
		return self.OnEscapeCode(PM, raw)
	}
	return nil
}

func (self *Loop) handle_rune(raw rune) error {
	if self.OnText != nil {
		return self.OnText(string(raw), false, self.escape_code_parser.InBracketedPaste())
	}
	return nil
}

func (self *Loop) handle_end_of_bracketed_paste() {
	if self.OnText != nil {
		self.OnText("", false, false)
	}
}

func (self *Loop) on_signal(s unix.Signal) error {
	switch s {
	case unix.SIGINT:
		return self.on_SIGINT()
	case unix.SIGPIPE:
		return self.on_SIGPIPE()
	case unix.SIGWINCH:
		return self.on_SIGWINCH()
	case unix.SIGTERM:
		return self.on_SIGTERM()
	case unix.SIGTSTP:
		return self.on_SIGTSTP()
	case unix.SIGHUP:
		return self.on_SIGHUP()
	default:
		return nil
	}
}

func (self *Loop) on_SIGINT() error {
	self.death_signal = unix.SIGINT
	self.keep_going = false
	return nil
}

func (self *Loop) on_SIGPIPE() error {
	return nil
}

func (self *Loop) on_SIGWINCH() error {
	self.screen_size.updated = false
	if self.OnResize != nil {
		old_size := self.screen_size
		err := self.update_screen_size()
		if err != nil {
			return err
		}
		return self.OnResize(old_size, self.screen_size)
	}
	return nil
}

func (self *Loop) on_SIGTERM() error {
	self.death_signal = unix.SIGTERM
	self.keep_going = false
	return nil
}

func (self *Loop) on_SIGHUP() error {
	self.death_signal = unix.SIGHUP
	self.keep_going = false
	return nil
}

func (self *Loop) run() (err error) {
	signal_channel := make(chan os.Signal, 256)
	handled_signals := []os.Signal{unix.SIGINT, unix.SIGTERM, unix.SIGTSTP, unix.SIGHUP, unix.SIGWINCH, unix.SIGPIPE}
	signal.Notify(signal_channel, handled_signals...)
	defer signal.Reset(handled_signals...)

	controlling_term, err := tty.OpenControllingTerm()
	if err != nil {
		return err
	}
	self.controlling_term = controlling_term
	defer func() {
		controlling_term.RestoreAndClose()
		self.controlling_term = nil
	}()
	err = controlling_term.ApplyOperations(tty.TCSANOW, tty.SetRaw)
	if err != nil {
		return nil
	}

	self.keep_going = true
	tty_read_channel := make(chan []byte)
	tty_write_channel := make(chan *write_msg, 1) // buffered so there is no race between initial queueing and startup of writer thread
	write_done_channel := make(chan IdType)
	tty_reading_done_channel := make(chan byte)
	self.wakeup_channel = make(chan byte, 256)
	self.pending_writes = make([]*write_msg, 0, 256)
	err_channel := make(chan error, 8)
	self.death_signal = SIGNULL
	self.escape_code_parser.Reset()
	self.exit_code = 0
	self.timers = make([]*timer, 0, 1)
	no_timeout_channel := make(<-chan time.Time)
	finalizer := ""

	w_r, w_w, err := os.Pipe()
	var r_r, r_w *os.File
	if err == nil {
		r_r, r_w, err = os.Pipe()
		if err != nil {
			w_r.Close()
			w_w.Close()
			return err
		}
	} else {
		return err
	}
	self.QueueWriteString(self.terminal_options.SetStateEscapeCodes())
	needs_reset_escape_codes := true

	defer func() {
		// notify tty reader that we are shutting down
		r_w.Close()
		close(tty_reading_done_channel)

		if self.OnFinalize != nil {
			finalizer += self.OnFinalize()
		}
		if finalizer != "" {
			self.QueueWriteString(finalizer)
		}
		if needs_reset_escape_codes {
			self.QueueWriteString(self.terminal_options.ResetStateEscapeCodes())
		}
		// flush queued data and wait for it to be written for a timeout, then wait for writer to shutdown
		flush_writer(w_w, tty_write_channel, write_done_channel, self.pending_writes, 2*time.Second)
		self.pending_writes = nil
		// wait for tty reader to exit cleanly
		for range tty_read_channel {
		}
	}()

	go write_to_tty(w_r, controlling_term, tty_write_channel, err_channel, write_done_channel)
	go read_from_tty(r_r, controlling_term, tty_read_channel, err_channel, tty_reading_done_channel)

	if self.OnInitialize != nil {
		finalizer, err = self.OnInitialize()
		if err != nil {
			return err
		}
	}

	self.Suspend = func() (func() error, error) {
		write_id := self.QueueWriteString(self.terminal_options.ResetStateEscapeCodes())
		needs_reset_escape_codes = false
		err := self.wait_for_write_to_complete(write_id, tty_write_channel, write_done_channel, 2*time.Second)
		if err != nil {
			return nil, err
		}
		resume, err := controlling_term.Suspend()
		if err != nil {
			return nil, err
		}
		return func() (err error) {
			err = resume()
			if err != nil {
				return
			}
			write_id = self.QueueWriteString(self.terminal_options.SetStateEscapeCodes())
			needs_reset_escape_codes = true
			return self.wait_for_write_to_complete(write_id, tty_write_channel, write_done_channel, 2*time.Second)
		}, nil

	}

	self.on_SIGTSTP = func() error {
		write_id := self.QueueWriteString(self.terminal_options.ResetStateEscapeCodes())
		needs_reset_escape_codes = false
		err := self.wait_for_write_to_complete(write_id, tty_write_channel, write_done_channel, 2*time.Second)
		if err != nil {
			return err
		}
		err = controlling_term.SuspendAndRun(func() error {
			unix.Kill(os.Getpid(), unix.SIGSTOP)
			time.Sleep(20 * time.Millisecond)
			return nil
		})
		if err != nil {
			return err
		}
		write_id = self.QueueWriteString(self.terminal_options.SetStateEscapeCodes())
		needs_reset_escape_codes = true
		err = self.wait_for_write_to_complete(write_id, tty_write_channel, write_done_channel, 2*time.Second)
		if err != nil {
			return err
		}
		if self.OnResumeFromStop != nil {
			return self.OnResumeFromStop()
		}
		return nil
	}

	for self.keep_going {
		self.flush_pending_writes(tty_write_channel)
		timeout_chan := no_timeout_channel
		if len(self.timers) > 0 {
			now := time.Now()
			err = self.dispatch_timers(now)
			if err != nil {
				return err
			}
			var timeout time.Duration
			if len(self.timers) > 0 {
				timeout = self.timers[0].deadline.Sub(now)
				if timeout < 0 {
					timeout = 0
				}
			}
			timeout_chan = time.After(timeout)
		}
		select {
		case <-timeout_chan:
		case <-self.wakeup_channel:
			for len(self.wakeup_channel) > 0 {
				<-self.wakeup_channel
			}
			if self.OnWakeup != nil {
				err = self.OnWakeup()
				if err != nil {
					return err
				}
			}
		case msg_id := <-write_done_channel:
			self.flush_pending_writes(tty_write_channel)
			if self.OnWriteComplete != nil {
				err = self.OnWriteComplete(msg_id)
				if err != nil {
					return err
				}
			}
		case rwerr := <-err_channel:
			return fmt.Errorf("Failed doing I/O with terminal: %w", rwerr)
		case s := <-signal_channel:
			err = self.on_signal(s.(unix.Signal))
			if err != nil {
				return err
			}
		case input_data, more := <-tty_read_channel:
			if !more {
				select {
				case rwerr := <-err_channel:
					return fmt.Errorf("Failed to read from terminal: %w", rwerr)
				default:
					return fmt.Errorf("Failed to read from terminal: %w", io.EOF)
				}
			}
			err := self.dispatch_input_data(input_data)
			if err != nil {
				return err
			}

		}
	}

	return nil
}
