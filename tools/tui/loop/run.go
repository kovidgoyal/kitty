// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"bytes"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var SIGNULL unix.Signal

func new_loop() *Loop {
	l := Loop{controlling_term: nil}
	l.terminal_options.Alternate_screen = true
	l.terminal_options.restore_colors = true
	l.terminal_options.focus_tracking = true
	l.terminal_options.in_band_resize_notification = true
	l.terminal_options.color_scheme_change_notification = false
	l.terminal_options.kitty_keyboard_mode = DISAMBIGUATE_KEYS | REPORT_ALTERNATE_KEYS | REPORT_ALL_KEYS_AS_ESCAPE_CODES | REPORT_TEXT_WITH_KEYS
	l.escape_code_parser.HandleCSI = l.handle_csi
	l.escape_code_parser.HandleOSC = l.handle_osc
	l.escape_code_parser.HandleDCS = l.handle_dcs
	l.escape_code_parser.HandleAPC = l.handle_apc
	l.escape_code_parser.HandleSOS = l.handle_sos
	l.escape_code_parser.HandlePM = l.handle_pm
	l.escape_code_parser.HandleRune = l.handle_rune
	l.escape_code_parser.HandleEndOfBracketedPaste = l.handle_end_of_bracketed_paste
	l.style_cache = make(map[string]func(...any) string)
	l.style_ctx.AllowEscapeCodes = true
	return &l
}

func is_temporary_error(err error) bool {
	return errors.Is(err, unix.EINTR) || errors.Is(err, unix.EAGAIN) || errors.Is(err, unix.EWOULDBLOCK) || errors.Is(err, io.ErrShortWrite)
}

func kill_self(sig unix.Signal) {
	_ = unix.Kill(os.Getpid(), sig)
	// Give the signal time to be delivered
	time.Sleep(20 * time.Millisecond)
}

func (self *Loop) set_pointer_shapes(ps []PointerShape) {
	self.pointer_shapes = ps
	if len(ps) > 0 {
		s := strings.Builder{}
		s.WriteString("\x1b]22;>")
		for i, x := range ps {
			s.WriteString(x.String())
			if i+1 < len(ps) {
				s.WriteByte(',')
			}
		}
		s.WriteString("\x1b\\")
		self.QueueWriteString(s.String())
	}
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

func (self *Loop) handle_csi(raw []byte) (err error) {
	csi := string(raw)
	if strings.HasSuffix(csi, "t") && strings.HasPrefix(csi, "48;") {
		if parts := strings.Split(csi[3:len(csi)-1], ";"); len(parts) > 3 {
			var parsed [4]int
			ok := true
			for i, x := range parts {
				x, _, _ = strings.Cut(x, ":")
				if parsed[i], err = strconv.Atoi(x); err != nil {
					ok = false
					break
				}
			}
			if ok {
				self.seen_inband_resize = true
				old_size := self.screen_size
				s := &self.screen_size
				s.updated = true
				s.HeightCells, s.WidthCells = uint(parsed[0]), uint(parsed[1])
				s.HeightPx, s.WidthPx = uint(parsed[2]), uint(parsed[3])
				s.CellWidth = s.WidthPx / s.WidthCells
				s.CellHeight = s.HeightPx / s.HeightCells
				if self.OnResize != nil {
					return self.OnResize(old_size, self.screen_size)
				}
				return nil
			}
		}
	} else if csi == "I" || csi == "O" {
		if self.OnFocusChange != nil {
			return self.OnFocusChange(csi == "I")
		}
		return nil
	}
	ke := KeyEventFromCSI(csi)
	if ke != nil {
		return self.handle_key_event(ke)
	}
	sz, err := self.ScreenSize()
	if err == nil {
		me := MouseEventFromCSI(csi, sz)
		if me != nil {
			return self.handle_mouse_event(me)
		}
	}
	if self.waiting_for_capabilities_response {
		if strings.HasPrefix(csi, "?") && strings.HasSuffix(csi, "c") {
			self.waiting_for_capabilities_response = false
			if self.OnCapabilitiesReceived != nil {
				if err = self.OnCapabilitiesReceived(self.TerminalCapabilities); err != nil {
					return err
				}
			}
		} else if strings.HasPrefix(csi, "?997;") && strings.HasSuffix(csi, "n") {
			switch csi[len(csi)-2] {
			case '1':
				self.TerminalCapabilities.ColorPreference = DARK_COLOR_PREFERENCE
			case '2':
				self.TerminalCapabilities.ColorPreference = LIGHT_COLOR_PREFERENCE
			}
			self.TerminalCapabilities.ColorPreferenceResponseReceived = true
		} else if strings.HasPrefix(csi, "?") && strings.HasSuffix(csi, "u") {
			self.TerminalCapabilities.KeyboardProtocol = true
			self.TerminalCapabilities.KeyboardProtocolResponseReceived = true
		}
	} else if self.terminal_options.color_scheme_change_notification && strings.HasPrefix(csi, "?997;") && strings.HasSuffix(csi, "n") {
		switch csi[len(csi)-2] {
		case '1':
			self.TerminalCapabilities.ColorPreference = DARK_COLOR_PREFERENCE
		case '2':
			self.TerminalCapabilities.ColorPreference = LIGHT_COLOR_PREFERENCE
		}
		self.TerminalCapabilities.ColorPreferenceResponseReceived = true
		if self.OnColorSchemeChange != nil {
			return self.OnColorSchemeChange(self.TerminalCapabilities.ColorPreference)
		}
	}
	if self.OnEscapeCode != nil {
		return self.OnEscapeCode(CSI, raw)
	}
	return nil
}

func is_click(a, b *MouseEvent) bool {
	if a.Event_type != MOUSE_PRESS || b.Event_type != MOUSE_RELEASE {
		return false
	}
	x := a.Cell.X - b.Cell.X
	y := a.Cell.Y - b.Cell.Y
	return x*x+y*y <= 4

}

func (self *Loop) handle_mouse_event(ev *MouseEvent) error {
	if self.OnMouseEvent != nil {
		err := self.OnMouseEvent(ev)
		if err != nil {
			return err
		}
		switch ev.Event_type {
		case MOUSE_PRESS:
			self.pending_mouse_events.WriteAllAndDiscardOld(*ev)
		case MOUSE_RELEASE:
			self.pending_mouse_events.WriteAllAndDiscardOld(*ev)
			if self.pending_mouse_events.Len() > 1 {
				events := self.pending_mouse_events.ReadAll()
				if is_click(&events[len(events)-2], &events[len(events)-1]) {
					e := events[len(events)-1]
					e.Event_type = MOUSE_CLICK
					err = self.OnMouseEvent(&e)
					if err != nil {
						return err
					}
				}
			}
		}
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
	if self.OnQueryResponse != nil && (bytes.HasPrefix(raw, utils.UnsafeStringToBytes("1+r")) || bytes.HasPrefix(raw, utils.UnsafeStringToBytes("0+r"))) {
		valid := raw[0] == '1'
		s := utils.NewSeparatorScanner(utils.UnsafeBytesToString(raw[3:]), ";")
		for s.Scan() {
			key, val, _ := strings.Cut(s.Text(), "=")
			if k, err := hex.DecodeString(key); err == nil {
				if bytes.HasPrefix(k, utils.UnsafeStringToBytes("kitty-query-")) {
					k = k[len("kitty-query-"):]
					if v, err := hex.DecodeString(val); err == nil {
						if err = self.OnQueryResponse(string(k), string(v), valid); err != nil {
							return err
						}
					}
				}
			}
		}
		return nil
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

func (self *Loop) handle_end_of_bracketed_paste() error {
	if self.OnText != nil {
		return self.OnText("", false, false)
	}
	return nil
}

func (self *Loop) on_signal(s unix.Signal) error {
	switch s {
	case unix.SIGINT:
		if self.OnSIGINT != nil {
			if handled, err := self.OnSIGINT(); handled {
				return err
			}
		}
		return self.on_SIGINT()
	case unix.SIGPIPE:
		return self.on_SIGPIPE()
	case unix.SIGWINCH:
		return self.on_SIGWINCH()
	case unix.SIGTERM:
		if self.OnSIGTERM != nil {
			if handled, err := self.OnSIGTERM(); handled {
				return err
			}
		}
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
	self.update_screen_size()
	if self.seen_inband_resize {
		return nil
	}
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

	controlling_term, err := tty.OpenControllingTerm(tty.SetRaw)
	if err != nil {
		return err
	}
	self.controlling_term = controlling_term
	defer func() {
		controlling_term.RestoreAndClose()
		self.controlling_term = nil
	}()

	self.keep_going = true
	self.seen_inband_resize = false
	self.pending_mouse_events = utils.NewRingBuffer[MouseEvent](4)
	// tty_write_channel is buffered so there is no race between initial
	// queueing and startup of writer thread and also as a performance
	// optimization to avoid copying unnecessarily to pending_writes
	self.tty_write_channel = make(chan write_msg, 512)
	self.write_msg_id_counter = 0
	write_done_channel := make(chan IdType)
	self.wakeup_channel = make(chan byte, 256)
	self.panic_channel = make(chan error)
	self.pending_writes = make([]write_msg, 0, 256)
	err_channel := make(chan error, 8)
	self.death_signal = SIGNULL
	self.escape_code_parser.Reset()
	self.exit_code = 0
	self.atomic_update_active = false
	self.timers, self.timers_temp = make([]*timer, 0, 8), make([]*timer, 0, 8)
	no_timeout_channel := make(<-chan time.Time)
	finalizer := ""

	var r_r, r_w, w_r, w_w *os.File
	var tty_reading_done_channel chan byte
	var tty_read_channel chan []byte
	var tty_leftover_read_channel chan []byte

	start_tty_reader := func() (err error) {
		r_r, r_w, err = os.Pipe()
		if err != nil {
			return err
		}
		tty_read_channel = make(chan []byte)
		tty_reading_done_channel = make(chan byte)
		tty_leftover_read_channel = make(chan []byte, 1)
		go read_from_tty(r_r, controlling_term, tty_read_channel, err_channel, tty_reading_done_channel, tty_leftover_read_channel)
		return
	}
	err = start_tty_reader()
	if err != nil {
		return err
	}
	w_r, w_w, err = os.Pipe() // these are closed in the writer thread and the shutdown defer in this thread
	if err != nil {
		return err
	}

	self.QueueWriteString(self.terminal_options.SetStateEscapeCodes())
	needs_reset_escape_codes := true

	shutdown_tty_reader := func() {
		// notify tty reader that we are shutting down
		if r_w != nil {
			r_w.Close()
			close(tty_reading_done_channel)
			r_w = nil
			tty_reading_done_channel = nil
		}
	}
	wait_for_tty_reader_to_quit := func() {
		// wait for tty reader to exit cleanly
		for range tty_read_channel {
		}
		if !self.waiting_for_capabilities_response {
			close(tty_leftover_read_channel)
			return
		}
		var pending_bytes []byte
		select {
		case msg, ok := <-tty_leftover_read_channel:
			if ok {
				pending_bytes = msg
			}
		default:
		}
		read_until_primary_device_attributes_response(controlling_term, pending_bytes, 2*time.Second)
	}

	defer func() {
		shutdown_tty_reader()

		if self.OnFinalize != nil {
			finalizer += self.OnFinalize()
		}
		if finalizer != "" {
			self.QueueWriteString(finalizer)
		}
		if needs_reset_escape_codes {
			self.ClearPointerShapes()
			self.QueueWriteString(self.terminal_options.ResetStateEscapeCodes())
		}
		// flush queued data and wait for it to be written for a timeout, then wait for writer to shutdown
		flush_writer(w_w, self.tty_write_channel, write_done_channel, self.pending_writes, 2*time.Second)
		self.pending_writes = nil
		self.tty_write_channel = nil
		wait_for_tty_reader_to_quit()
	}()

	go write_to_tty(w_r, controlling_term, self.tty_write_channel, err_channel, write_done_channel)

	if self.OnInitialize != nil {
		finalizer, err = self.OnInitialize()
		if err != nil {
			return err
		}
	}

	self.SuspendAndRun = func(run func() error) (err error) {
		ps := self.ClearPointerShapes()
		write_id := self.QueueWriteString(self.terminal_options.ResetStateEscapeCodes())
		needs_reset_escape_codes = false
		if err = self.wait_for_write_to_complete(write_id, self.tty_write_channel, write_done_channel, 2*time.Second); err != nil {
			return err
		}
		shutdown_tty_reader()
		wait_for_tty_reader_to_quit()
		resume, err := controlling_term.Suspend()
		if err != nil {
			return err
		}
		if err = run(); err != nil {
			return err
		}
		if err = start_tty_reader(); err != nil {
			return err
		}
		if err = resume(); err != nil {
			return err
		}
		write_id = self.QueueWriteString(self.terminal_options.SetStateEscapeCodes())
		self.set_pointer_shapes(ps)
		needs_reset_escape_codes = true
		return self.wait_for_write_to_complete(write_id, self.tty_write_channel, write_done_channel, 2*time.Second)
	}

	self.on_SIGTSTP = func() error {
		ps := self.ClearPointerShapes()
		write_id := self.QueueWriteString(self.terminal_options.ResetStateEscapeCodes())
		needs_reset_escape_codes = false
		err := self.wait_for_write_to_complete(write_id, self.tty_write_channel, write_done_channel, 2*time.Second)
		if err != nil {
			return err
		}
		err = controlling_term.SuspendAndRun(func() error {
			_ = unix.Kill(os.Getpid(), unix.SIGSTOP)
			time.Sleep(20 * time.Millisecond)
			return nil
		})
		if err != nil {
			return err
		}
		write_id = self.QueueWriteString(self.terminal_options.SetStateEscapeCodes())
		self.set_pointer_shapes(ps)
		needs_reset_escape_codes = true
		err = self.wait_for_write_to_complete(write_id, self.tty_write_channel, write_done_channel, 2*time.Second)
		if err != nil {
			return err
		}
		if self.OnResumeFromStop != nil {
			return self.OnResumeFromStop()
		}
		return nil
	}

	for self.keep_going {
		self.flush_pending_writes(self.tty_write_channel)
		timeout_chan := no_timeout_channel
		if len(self.timers) > 0 {
			now := time.Now()
			err = self.dispatch_timers(now)
			if err != nil {
				return err
			}
			var timeout time.Duration
			if len(self.timers) > 0 {
				timeout = max(0, self.timers[0].deadline.Sub(now))
			}
			timeout_chan = time.After(timeout)
		}
		select {
		case <-timeout_chan:
		case p := <-self.panic_channel:
			return p
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
			self.flush_pending_writes(self.tty_write_channel)
			if self.OnWriteComplete != nil {
				err = self.OnWriteComplete(msg_id, msg_id < self.write_msg_id_counter)
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
