// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"kitty/tools/tty"
	"os"
	"os/signal"
	"runtime/debug"
	"sort"
	"time"

	"golang.org/x/sys/unix"

	"kitty/tools/utils"
	"kitty/tools/wcswidth"
)

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

func is_temporary_error(err error) bool {
	return errors.Is(err, unix.EINTR) || errors.Is(err, unix.EAGAIN) || errors.Is(err, unix.EWOULDBLOCK) || errors.Is(err, io.ErrShortWrite)
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

type ScreenSize struct {
	WidthCells, HeightCells, WidthPx, HeightPx, CellWidth, CellHeight uint
	updated                                                           bool
}

type IdType uint64
type TimerCallback func(loop *Loop, timer_id IdType) error

type timer struct {
	interval time.Duration
	deadline time.Time
	repeats  bool
	id       IdType
	callback TimerCallback
}

func (self *timer) update_deadline(now time.Time) {
	self.deadline = now.Add(self.interval)
}

var SIGNULL unix.Signal

type write_msg struct {
	id    IdType
	bytes []byte
	str   string
}

func (self *write_msg) String() string {
	return fmt.Sprintf("write_msg{%v %#v %#v}", self.id, string(self.bytes), self.str)
}

type Loop struct {
	controlling_term                                                   *tty.Term
	terminal_options                                                   TerminalStateOptions
	screen_size                                                        ScreenSize
	escape_code_parser                                                 wcswidth.EscapeCodeParser
	keep_going                                                         bool
	death_signal                                                       unix.Signal
	exit_code                                                          int
	timers                                                             []*timer
	timer_id_counter, write_msg_id_counter                             IdType
	tty_read_channel                                                   chan []byte
	tty_write_channel                                                  chan *write_msg
	write_done_channel                                                 chan IdType
	err_channel                                                        chan error
	tty_writing_done_channel, tty_reading_done_channel, wakeup_channel chan byte
	pending_writes                                                     []*write_msg

	// Callbacks

	// Called when the terminal has been fully setup. Any string returned is sent to
	// the terminal on shutdown
	OnInitialize func(loop *Loop) (string, error)

	// Called when a key event happens
	OnKeyEvent func(loop *Loop, event *KeyEvent) error

	// Called when text is received either from a key event or directly from the terminal
	OnText func(loop *Loop, text string, from_key_event bool, in_bracketed_paste bool) error

	// Called when the terminal is resize
	OnResize func(loop *Loop, old_size ScreenSize, new_size ScreenSize) error

	// Called when writing is done
	OnWriteComplete func(loop *Loop, msg_id IdType) error

	// Called when a response to an rc command is received
	OnRCResponse func(loop *Loop, data []byte) error

	// Called when any input form tty is received
	OnReceivedData func(loop *Loop, data []byte) error
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
	if self.OnRCResponse != nil && bytes.HasPrefix(raw, []byte("@kitty-cmd")) {
		return self.OnRCResponse(self, raw[len("@kitty-cmd"):])
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
		return self.OnText(self, string(raw), false, self.escape_code_parser.InBracketedPaste())
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
		return self.OnResize(self, old_size, self.screen_size)
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

func CreateLoop() (*Loop, error) {
	l := Loop{controlling_term: nil, timers: make([]*timer, 0)}
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

func (self *Loop) AddTimer(interval time.Duration, repeats bool, callback TimerCallback) IdType {
	self.timer_id_counter++
	t := timer{interval: interval, repeats: repeats, callback: callback, id: self.timer_id_counter}
	t.update_deadline(time.Now())
	self.timers = append(self.timers, &t)
	self.sort_timers()
	return t.id
}

func (self *Loop) RemoveTimer(id IdType) bool {
	for i := 0; i < len(self.timers); i++ {
		if self.timers[i].id == id {
			self.timers = append(self.timers[:i], self.timers[i+1:]...)
			return true
		}
	}
	return false
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

func (self *Loop) ScreenSize() (ScreenSize, error) {
	if self.screen_size.updated {
		return self.screen_size, nil
	}
	err := self.update_screen_size()
	return self.screen_size, err
}

func kill_self(sig unix.Signal) {
	unix.Kill(os.Getpid(), sig)
	// Give the signal time to be delivered
	time.Sleep(20 * time.Millisecond)
}

func (self *Loop) KillIfSignalled() {
	if self.death_signal != SIGNULL {
		kill_self(self.death_signal)
	}
}

func (self *Loop) DebugPrintln(args ...interface{}) {
	if self.controlling_term != nil {
		self.controlling_term.DebugPrintln(args...)
	}
}

func (self *Loop) Run() (err error) {
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
	self.tty_read_channel = make(chan []byte)
	self.tty_write_channel = make(chan *write_msg, 1) // buffered so there is no race between initial queueing and startup of writer thread
	self.write_done_channel = make(chan IdType)
	self.tty_writing_done_channel = make(chan byte)
	self.tty_reading_done_channel = make(chan byte)
	self.wakeup_channel = make(chan byte, 256)
	self.pending_writes = make([]*write_msg, 0, 256)
	self.err_channel = make(chan error, 8)
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
		close(self.tty_reading_done_channel)

		if finalizer != "" {
			self.QueueWriteString(finalizer)
		}
		self.QueueWriteBytesDangerous(self.terminal_options.ResetStateEscapeCodes())
		// flush queued data and wait for it to be written for a timeout, then wait for writer to shutdown
		flush_writer(w_w, self.tty_write_channel, self.tty_writing_done_channel, self.pending_writes, 2*time.Second)
		self.pending_writes = nil
		// wait for tty reader to exit cleanly
		for more := true; more; _, more = <-self.tty_read_channel {
		}
	}()

	go write_to_tty(w_r, self.controlling_term, self.tty_write_channel, self.err_channel, self.write_done_channel, self.tty_writing_done_channel)
	go read_from_tty(r_r, self.controlling_term, self.tty_read_channel, self.err_channel, self.tty_reading_done_channel)

	if self.OnInitialize != nil {
		finalizer, err = self.OnInitialize(self)
		if err != nil {
			return err
		}
	}

	for self.keep_going {
		self.queue_write_to_tty(nil)
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
		case msg_id := <-self.write_done_channel:
			self.queue_write_to_tty(nil)
			if self.OnWriteComplete != nil {
				err = self.OnWriteComplete(self, msg_id)
				if err != nil {
					return err
				}
			}
		case s := <-sigchnl:
			err = self.on_signal(s.(unix.Signal))
			if err != nil {
				return err
			}
		case input_data, more := <-self.tty_read_channel:
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

func (self *Loop) dispatch_input_data(data []byte) error {
	if self.OnReceivedData != nil {
		err := self.OnReceivedData(self, data)
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

func (self *Loop) print_stack() {
	self.DebugPrintln(string(debug.Stack()))
}

func (self *Loop) queue_write_to_tty(data *write_msg) {
	for len(self.pending_writes) > 0 {
		select {
		case self.tty_write_channel <- self.pending_writes[0]:
			n := copy(self.pending_writes, self.pending_writes[1:])
			self.pending_writes = self.pending_writes[:n]
		default:
			if data != nil {
				self.pending_writes = append(self.pending_writes, data)
			}
			return
		}
	}
	if data != nil {
		select {
		case self.tty_write_channel <- data:
		default:
			self.pending_writes = append(self.pending_writes, data)
		}
	}
}

func (self *Loop) WakeupMainThread() {
	self.wakeup_channel <- 1
}

func (self *Loop) QueueWriteString(data string) IdType {
	self.write_msg_id_counter++
	msg := write_msg{str: data, id: self.write_msg_id_counter}
	self.queue_write_to_tty(&msg)
	return msg.id
}

// This is dangerous as it is upto the calling code
// to ensure the data in the underlying array does not change
func (self *Loop) QueueWriteBytesDangerous(data []byte) IdType {
	self.write_msg_id_counter++
	msg := write_msg{bytes: data, id: self.write_msg_id_counter}
	self.queue_write_to_tty(&msg)
	return msg.id
}

func (self *Loop) QueueWriteBytesCopy(data []byte) IdType {
	d := make([]byte, len(data))
	copy(d, data)
	return self.QueueWriteBytesDangerous(d)
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

func read_from_tty(pipe_r *os.File, term *tty.Term, results_channel chan<- []byte, err_channel chan<- error, quit_channel <-chan byte) {
	keep_going := true
	pipe_fd := int(pipe_r.Fd())
	tty_fd := term.Fd()
	selector := CreateSelect(2)
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

type write_dispatcher struct {
	str       string
	bytes     []byte
	is_string bool
	is_empty  bool
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
	job_channel <-chan *write_msg, err_channel chan<- error, write_done_channel chan<- IdType, completed_channel chan<- byte,
) {
	keep_going := true
	defer func() {
		pipe_r.Close()
		close(completed_channel)
	}()
	selector := CreateSelect(2)
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

func flush_writer(pipe_w *os.File, tty_write_channel chan<- *write_msg, tty_writing_done_channel <-chan byte, pending_writes []*write_msg, timeout time.Duration) {
	writer_quit := false
	defer func() {
		if tty_write_channel != nil {
			close(tty_write_channel)
			tty_write_channel = nil
		}
		pipe_w.Close()
		if !writer_quit {
			<-tty_writing_done_channel
			writer_quit = true
		}
	}()
	deadline := time.Now().Add(timeout)
	for len(pending_writes) > 0 {
		timeout = deadline.Sub(time.Now())
		if timeout <= 0 {
			return
		}
		select {
		case <-time.After(timeout):
			return
		case tty_write_channel <- pending_writes[0]:
			pending_writes = pending_writes[1:]
		}
	}
	close(tty_write_channel)
	tty_write_channel = nil
	timeout = deadline.Sub(time.Now())
	if timeout <= 0 {
		return
	}
	select {
	case <-tty_writing_done_channel:
		writer_quit = true
	case <-time.After(timeout):
	}
	return
}

func (self *Loop) dispatch_timers(now time.Time) error {
	updated := false
	remove := make(map[IdType]bool, 0)
	for _, t := range self.timers {
		if now.After(t.deadline) {
			err := t.callback(self, t.id)
			if err != nil {
				return err
			}
			if t.repeats {
				t.update_deadline(now)
				updated = true
			} else {
				remove[t.id] = true
			}
		}
	}
	if len(remove) > 0 {
		timers := make([]*timer, len(self.timers)-len(remove))
		for _, t := range self.timers {
			if !remove[t.id] {
				timers = append(timers, t)
			}
		}
		self.timers = timers
	}
	if updated {
		self.sort_timers()
	}
	return nil
}

func (self *Loop) sort_timers() {
	sort.SliceStable(self.timers, func(a, b int) bool { return self.timers[a].deadline.Before(self.timers[b].deadline) })
}
