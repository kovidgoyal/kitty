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
)

var SIGNULL unix.Signal

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
	if self.controlling_term != nil {
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
	return nil
}

func (self *Loop) handle_key_event(ev *KeyEvent) error {
	// self.DebugPrintln(ev)
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
	return nil
}

func (self *Loop) handle_dcs(raw []byte) error {
	if self.OnRCResponse != nil && bytes.HasPrefix(raw, []byte("@kitty-cmd")) {
		return self.OnRCResponse(raw[len("@kitty-cmd"):])
	}
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
		return self.OnText(string(raw), false, self.escape_code_parser.InBracketedPaste())
	}
	return nil
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

func (self *Loop) on_SIGTSTP() error {
	return nil
}

func (self *Loop) on_SIGHUP() error {
	self.death_signal = unix.SIGHUP
	self.keep_going = false
	return nil
}

func (self *Loop) run() (err error) {
	sigchnl := make(chan os.Signal, 256)
	handled_signals := []os.Signal{unix.SIGINT, unix.SIGTERM, unix.SIGTSTP, unix.SIGHUP, unix.SIGWINCH, unix.SIGPIPE}
	signal.Notify(sigchnl, handled_signals...)
	defer signal.Reset(handled_signals...)

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
	self.QueueWriteBytesDangerous(self.terminal_options.SetStateEscapeCodes())

	defer func() {
		// notify tty reader that we are shutting down
		r_w.Close()
		close(tty_reading_done_channel)

		if finalizer != "" {
			self.QueueWriteString(finalizer)
		}
		self.QueueWriteBytesDangerous(self.terminal_options.ResetStateEscapeCodes())
		// flush queued data and wait for it to be written for a timeout, then wait for writer to shutdown
		flush_writer(w_w, tty_write_channel, write_done_channel, self.pending_writes, 2*time.Second)
		self.pending_writes = nil
		// wait for tty reader to exit cleanly
		for more := true; more; _, more = <-tty_read_channel {
		}
	}()

	go write_to_tty(w_r, self.controlling_term, tty_write_channel, err_channel, write_done_channel)
	go read_from_tty(r_r, self.controlling_term, tty_read_channel, err_channel, tty_reading_done_channel)

	if self.OnInitialize != nil {
		finalizer, err = self.OnInitialize()
		if err != nil {
			return err
		}
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
			timeout := self.timers[0].deadline.Sub(now)
			if timeout < 0 {
				timeout = 0
			}
			timeout_chan = time.After(timeout)
		}
		select {
		case <-timeout_chan:
		case <-self.wakeup_channel:
			for len(self.wakeup_channel) > 0 {
				<-self.wakeup_channel
			}
		case msg_id := <-write_done_channel:
			self.flush_pending_writes(tty_write_channel)
			if self.OnWriteComplete != nil {
				err = self.OnWriteComplete(msg_id)
				if err != nil {
					return err
				}
			}
		case s := <-sigchnl:
			err = self.on_signal(s.(unix.Signal))
			if err != nil {
				return err
			}
		case input_data, more := <-tty_read_channel:
			if !more {
				return io.EOF
			}
			err := self.dispatch_input_data(input_data)
			if err != nil {
				return err
			}

		}
	}

	return nil
}
