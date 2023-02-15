// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"encoding/base64"
	"fmt"
	"kitty/tools/tty"
	"strings"
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
type EscapeCodeType int

const (
	CSI EscapeCodeType = iota
	DCS
	OSC
	APC
	SOS
	PM
)

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
	timers, timers_temp                    []*timer
	timer_id_counter, write_msg_id_counter IdType
	wakeup_channel                         chan byte
	pending_writes                         []*write_msg
	on_SIGTSTP                             func() error

	// Suspend the loop restoring terminal state. Call the return resume function to restore the loop
	Suspend func() (func() error, error)

	// Callbacks

	// Called when the terminal has been fully setup. Any string returned is sent to
	// the terminal on shutdown
	OnInitialize func() (string, error)

	// Called just before the loop shuts down. Any returned string is written to the terminal before
	// shutdown
	OnFinalize func() string

	// Called when a key event happens
	OnKeyEvent func(event *KeyEvent) error

	// Called when text is received either from a key event or directly from the terminal
	// Called with an empty string when bracketed paste ends
	OnText func(text string, from_key_event bool, in_bracketed_paste bool) error

	// Called when the terminal is resized
	OnResize func(old_size ScreenSize, new_size ScreenSize) error

	// Called when writing is done
	OnWriteComplete func(msg_id IdType) error

	// Called when a response to an rc command is received
	OnRCResponse func(data []byte) error

	// Called when any input from tty is received
	OnReceivedData func(data []byte) error

	// Called when an escape code is received that is not handled by any other handler
	OnEscapeCode func(EscapeCodeType, []byte) error

	// Called when resuming from a SIGTSTP or Ctrl-z
	OnResumeFromStop func() error

	// Called when main loop is woken up
	OnWakeup func() error
}

func New(options ...func(self *Loop)) (*Loop, error) {
	l := new_loop()
	for _, f := range options {
		f(l)
	}
	return l, nil
}

func (self *Loop) AddTimer(interval time.Duration, repeats bool, callback TimerCallback) (IdType, error) {
	return self.add_timer(interval, repeats, callback)
}

func (self *Loop) RemoveTimer(id IdType) bool {
	return self.remove_timer(id)
}

func (self *Loop) NoAlternateScreen() *Loop {
	self.terminal_options.alternate_screen = false
	return self
}

func NoAlternateScreen(self *Loop) {
	self.terminal_options.alternate_screen = false
}

func (self *Loop) OnlyDisambiguateKeys() *Loop {
	self.terminal_options.kitty_keyboard_mode = 0b1
	return self
}

func OnlyDisambiguateKeys(self *Loop) {
	self.terminal_options.kitty_keyboard_mode = 0b1
}

func (self *Loop) FullKeyboardProtocol() *Loop {
	self.terminal_options.kitty_keyboard_mode = 0b11111
	return self
}

func FullKeyboardProtocol(self *Loop) {
	self.terminal_options.kitty_keyboard_mode = 0b11111
}

func (self *Loop) MouseTrackingMode(mt MouseTracking) *Loop {
	self.terminal_options.mouse_tracking = mt
	return self
}

func MouseTrackingMode(self *Loop, mt MouseTracking) {
	self.terminal_options.mouse_tracking = mt
}

func NoMouseTracking(self *Loop) {
	self.terminal_options.mouse_tracking = NO_MOUSE_TRACKING
}

func (self *Loop) NoMouseTracking() *Loop {
	self.terminal_options.mouse_tracking = NO_MOUSE_TRACKING
	return self
}

func (self *Loop) NoRestoreColors() *Loop {
	self.terminal_options.restore_colors = false
	return self
}

func NoRestoreColors(self *Loop) {
	self.terminal_options.restore_colors = false
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

func (self *Loop) Println(args ...any) {
	self.QueueWriteString(fmt.Sprint(args...))
	self.QueueWriteString("\r\n")
}

func (self *Loop) SaveCursorPosition() {
	self.QueueWriteString("\x1b7")
}

func (self *Loop) RestoreCursorPosition() {
	self.QueueWriteString("\x1b8")
}

func (self *Loop) Printf(format string, args ...any) {
	format = strings.ReplaceAll(format, "\n", "\r\n")
	self.QueueWriteString(fmt.Sprintf(format, args...))
}

func (self *Loop) DebugPrintln(args ...any) {
	if self.controlling_term != nil {
		const limit = 2048
		msg := fmt.Sprintln(args...)
		for i := 0; i < len(msg); i += limit {
			end := i + limit
			if end > len(msg) {
				end = len(msg)
			}
			self.QueueWriteString("\x1bP@kitty-print|")
			self.QueueWriteString(base64.StdEncoding.EncodeToString([]byte(msg[i:end])))
			self.QueueWriteString("\x1b\\")
		}
	}
}

func (self *Loop) Run() (err error) {
	return self.run()
}

func (self *Loop) WakeupMainThread() bool {
	select {
	case self.wakeup_channel <- 1:
		return true
	default:
		return false
	}
}

func (self *Loop) QueueWriteString(data string) IdType {
	self.write_msg_id_counter++
	msg := write_msg{str: data, bytes: nil, id: self.write_msg_id_counter}
	self.add_write_to_pending_queue(&msg)
	return msg.id
}

// This is dangerous as it is upto the calling code
// to ensure the data in the underlying array does not change
func (self *Loop) UnsafeQueueWriteBytes(data []byte) IdType {
	self.write_msg_id_counter++
	msg := write_msg{bytes: data, id: self.write_msg_id_counter}
	self.add_write_to_pending_queue(&msg)
	return msg.id
}

func (self *Loop) QueueWriteBytesCopy(data []byte) IdType {
	d := make([]byte, len(data))
	copy(d, data)
	return self.UnsafeQueueWriteBytes(d)
}

func (self *Loop) ExitCode() int {
	return self.exit_code
}

func (self *Loop) Beep() {
	self.QueueWriteString("\a")
}

func (self *Loop) StartAtomicUpdate() {
	self.QueueWriteString(PENDING_UPDATE.EscapeCodeToSet())
}

func (self *Loop) EndAtomicUpdate() {
	self.QueueWriteString(PENDING_UPDATE.EscapeCodeToReset())
}

func (self *Loop) SetCursorShape(shape CursorShapes, blink bool) {
	self.QueueWriteString(CursorShape(shape, blink))
}

func (self *Loop) SetCursorVisible(visible bool) {
	if visible {
		self.QueueWriteString(DECTCEM.EscapeCodeToSet())
	} else {
		self.QueueWriteString(DECTCEM.EscapeCodeToReset())
	}
}

const MoveCursorToTemplate = "\x1b[%d;%dH"

func (self *Loop) MoveCursorTo(x, y int) {
	if x > 0 && y > 0 {
		self.QueueWriteString(fmt.Sprintf(MoveCursorToTemplate, y, x))
	}
}

func (self *Loop) MoveCursorHorizontally(amt int) {
	if amt != 0 {
		suffix := "C"
		if amt < 0 {
			suffix = "D"
			amt *= -1
		}
		self.QueueWriteString(fmt.Sprintf("\x1b[%d%s", amt, suffix))
	}
}

func (self *Loop) MoveCursorVertically(amt int) {
	if amt != 0 {
		suffix := "B"
		if amt < 0 {
			suffix = "A"
			amt *= -1
		}
		self.QueueWriteString(fmt.Sprintf("\x1b[%d%s", amt, suffix))
	}
}

func (self *Loop) ClearToEndOfScreen() {
	self.QueueWriteString("\x1b[J")
}

func (self *Loop) ClearToEndOfLine() {
	self.QueueWriteString("\x1b[K")
}

func (self *Loop) StartBracketedPaste() {
	self.QueueWriteString(BRACKETED_PASTE.EscapeCodeToSet())
}

func (self *Loop) EndBracketedPaste() {
	self.QueueWriteString(BRACKETED_PASTE.EscapeCodeToReset())
}

func (self *Loop) AllowLineWrapping(allow bool) {
	if allow {
		self.QueueWriteString(DECAWM.EscapeCodeToSet())
	} else {
		self.QueueWriteString(DECAWM.EscapeCodeToReset())
	}
}

func (self *Loop) SetWindowTitle(title string) {
	title = strings.ReplaceAll(title, "\033", "")
	title = strings.ReplaceAll(title, "\x9c", "")
	self.QueueWriteString("\033]2;" + title + "\033\\")
}

func (self *Loop) ClearScreen() {
	self.QueueWriteString("\x1b[H\x1b[2J")
}

func (self *Loop) SendOverlayReady() {
	self.QueueWriteString("\x1bP@kitty-overlay-ready|\x1b\\")
}

func (self *Loop) Quit(exit_code int) {
	self.exit_code = exit_code
	self.keep_going = false
}
