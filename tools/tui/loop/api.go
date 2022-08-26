// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"kitty/tools/tty"
	"time"

	"golang.org/x/sys/unix"

	"kitty/tools/wcswidth"
)

type ScreenSize struct {
	WidthCells, HeightCells, WidthPx, HeightPx, CellWidth, CellHeight uint
	updated                                                           bool
}

type IdType uint64
type TimerCallback func(timer_id IdType) error

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

type Loop struct {
	controlling_term                       *tty.Term
	terminal_options                       TerminalStateOptions
	screen_size                            ScreenSize
	escape_code_parser                     wcswidth.EscapeCodeParser
	keep_going                             bool
	death_signal                           unix.Signal
	exit_code                              int
	timers                                 []*timer
	timer_id_counter, write_msg_id_counter IdType
	wakeup_channel                         chan byte
	pending_writes                         []*write_msg

	// Callbacks

	// Called when the terminal has been fully setup. Any string returned is sent to
	// the terminal on shutdown
	OnInitialize func() (string, error)

	// Called when a key event happens
	OnKeyEvent func(event *KeyEvent) error

	// Called when text is received either from a key event or directly from the terminal
	OnText func(text string, from_key_event bool, in_bracketed_paste bool) error

	// Called when the terminal is resized
	OnResize func(old_size ScreenSize, new_size ScreenSize) error

	// Called when writing is done
	OnWriteComplete func(msg_id IdType) error

	// Called when a response to an rc command is received
	OnRCResponse func(data []byte) error

	// Called when any input from tty is received
	OnReceivedData func(data []byte) error
}

func New() (*Loop, error) {
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
	return self.run()
}

func (self *Loop) WakeupMainThread() {
	self.wakeup_channel <- 1
}

func (self *Loop) QueueWriteString(data string) IdType {
	self.write_msg_id_counter++
	msg := write_msg{str: data, id: self.write_msg_id_counter}
	self.add_write_to_pending_queue(&msg)
	return msg.id
}

// This is dangerous as it is upto the calling code
// to ensure the data in the underlying array does not change
func (self *Loop) QueueWriteBytesDangerous(data []byte) IdType {
	self.write_msg_id_counter++
	msg := write_msg{bytes: data, id: self.write_msg_id_counter}
	self.add_write_to_pending_queue(&msg)
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
