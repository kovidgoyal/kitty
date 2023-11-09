// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"encoding/base64"
	"fmt"
	"os"
	"runtime"
	"strings"
	"time"

	"golang.org/x/sys/unix"

	"kitty/tools/tty"
	"kitty/tools/utils"
	"kitty/tools/utils/style"
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
	pending_writes                         []write_msg
	tty_write_channel                      chan write_msg
	pending_mouse_events                   *utils.RingBuffer[MouseEvent]
	on_SIGTSTP                             func() error
	style_cache                            map[string]func(...any) string
	style_ctx                              style.Context
	atomic_update_active                   bool
	pointer_shapes                         []PointerShape

	// Suspend the loop restoring terminal state, and run the provided function. When it returns terminal state is
	// put back to what it was before suspending unless the function returns an error or an error occurs saving/restoring state.
	SuspendAndRun func(func() error) error

	// Callbacks

	// Called when the terminal has been fully setup. Any string returned is sent to
	// the terminal on shutdown
	OnInitialize func() (string, error)

	// Called just before the loop shuts down. Any returned string is written to the terminal before
	// shutdown
	OnFinalize func() string

	// Called when a key event happens
	OnKeyEvent func(event *KeyEvent) error

	// Called when a mouse event happens
	OnMouseEvent func(event *MouseEvent) error

	// Called when text is received either from a key event or directly from the terminal
	// Called with an empty string when bracketed paste ends
	OnText func(text string, from_key_event bool, in_bracketed_paste bool) error

	// Called when the terminal is resized
	OnResize func(old_size ScreenSize, new_size ScreenSize) error

	// Called when writing is done
	OnWriteComplete func(msg_id IdType, has_pending_writes bool) error

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

	// Called on SIGINT return true if you wish to handle it yourself
	OnSIGINT func() (bool, error)

	// Called on SIGTERM return true if you wish to handle it yourself
	OnSIGTERM func() (bool, error)
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

func (self *Loop) CallSoon(callback TimerCallback) (IdType, error) {
	return self.add_timer(0, false, callback)
}

func (self *Loop) RemoveTimer(id IdType) bool {
	return self.remove_timer(id)
}

func (self *Loop) NoAlternateScreen() *Loop {
	self.terminal_options.Alternate_screen = false
	return self
}

func NoAlternateScreen(self *Loop) {
	self.terminal_options.Alternate_screen = false
}

func (self *Loop) OnlyDisambiguateKeys() *Loop {
	self.terminal_options.kitty_keyboard_mode = DISAMBIGUATE_KEYS
	return self
}

func OnlyDisambiguateKeys(self *Loop) {
	self.terminal_options.kitty_keyboard_mode = DISAMBIGUATE_KEYS
}

func (self *Loop) FullKeyboardProtocol() *Loop {
	self.terminal_options.kitty_keyboard_mode = FULL_KEYBOARD_PROTOCOL
	return self
}

func FullKeyboardProtocol(self *Loop) {
	self.terminal_options.kitty_keyboard_mode = FULL_KEYBOARD_PROTOCOL
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
	self.QueueWriteString(fmt.Sprintln(args...))
	self.QueueWriteString("\r")
}

func (self *Loop) SprintStyled(style string, args ...any) string {
	f := self.style_cache[style]
	if f == nil {
		f = self.style_ctx.SprintFunc(style)
		self.style_cache[style] = f
	}
	return f(args...)
}

func (self *Loop) PrintStyled(style string, args ...any) {
	self.QueueWriteString(self.SprintStyled(style, args...))
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
	defer func() {
		if r := recover(); r != nil {
			pcs := make([]uintptr, 256)
			n := runtime.Callers(2, pcs)
			frames := runtime.CallersFrames(pcs[:n])
			err = fmt.Errorf("Panicked: %s", r)
			fmt.Fprintf(os.Stderr, "\r\nPanicked with error: %s\r\nStacktrace (most recent call first):\r\n", r)
			found_first_frame := false
			for frame, more := frames.Next(); more; frame, more = frames.Next() {
				if !found_first_frame {
					if strings.HasPrefix(frame.Function, "runtime.") {
						continue
					}
					found_first_frame = true
				}
				fmt.Fprintf(os.Stderr, "%s\r\n\t%s:%d\r\n", frame.Function, frame.File, frame.Line)
			}
			if self.terminal_options.Alternate_screen {
				term, err := tty.OpenControllingTerm(tty.SetRaw)
				if err == nil {
					defer term.RestoreAndClose()
					fmt.Println("Press any key to exit.\r")
					buf := make([]byte, 16)
					_, _ = term.Read(buf)
				}
			}
		}
	}()
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
	self.add_write_to_pending_queue(msg)
	return msg.id
}

// This is dangerous as it is upto the calling code
// to ensure the data in the underlying array does not change
func (self *Loop) UnsafeQueueWriteBytes(data []byte) IdType {
	self.write_msg_id_counter++
	msg := write_msg{bytes: data, id: self.write_msg_id_counter}
	self.add_write_to_pending_queue(msg)
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
	if self.atomic_update_active {
		self.EndAtomicUpdate()
	}
	self.QueueWriteString(PENDING_UPDATE.EscapeCodeToSet())
	self.atomic_update_active = true
}

func (self *Loop) IsAtomicUpdateActive() bool { return self.atomic_update_active }

func (self *Loop) EndAtomicUpdate() {
	if self.atomic_update_active {
		self.QueueWriteString(PENDING_UPDATE.EscapeCodeToReset())
		self.atomic_update_active = false
	}
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

func (self *Loop) MoveCursorTo(x, y int) { // 1, 1 is top left
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

func EscapeCodeToSetWindowTitle(title string) string {
	title = wcswidth.StripEscapeCodes(title)
	return "\033]2;" + title + "\033\\"
}

func (self *Loop) SetWindowTitle(title string) {
	self.QueueWriteString(EscapeCodeToSetWindowTitle(title))
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

type DefaultColor int

const (
	BACKGROUND   DefaultColor = 11
	FOREGROUND   DefaultColor = 10
	CURSOR       DefaultColor = 12
	SELECTION_BG DefaultColor = 17
	SELECTION_FG DefaultColor = 19
)

func (self *Loop) SetDefaultColor(which DefaultColor, val style.RGBA) {
	self.QueueWriteString(fmt.Sprintf("\033]%d;%s\033\\", int(which), val.AsRGBSharp()))
}

func (self *Loop) copy_text_to(text, dest string) {
	self.QueueWriteString("\x1b]52;" + dest + ";")
	self.QueueWriteString(base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(text)))
	self.QueueWriteString("\x1b\\")
}

func (self *Loop) CopyTextToPrimarySelection(text string) {
	self.copy_text_to(text, "p")
}

func (self *Loop) CopyTextToClipboard(text string) {
	self.copy_text_to(text, "c")
}

func (self *Loop) PushPointerShape(s PointerShape) {
	self.pointer_shapes = append(self.pointer_shapes, s)
	self.QueueWriteString("\x1b]22;" + s.String() + "\x1b\\")
}

func (self *Loop) PopPointerShape() {
	if len(self.pointer_shapes) > 0 {
		self.pointer_shapes = self.pointer_shapes[:len(self.pointer_shapes)-1]
		self.QueueWriteString("\x1b]22;<\x1b\\")
	}
}

func (self *Loop) ClearPointerShapes() (ans []PointerShape) {
	ans = self.pointer_shapes
	for i := len(self.pointer_shapes) - 1; i >= 0; i-- {
		self.QueueWriteString("\x1b]22;<\x1b\\")
	}
	self.pointer_shapes = nil
	return ans
}

func (self *Loop) CurrentPointerShape() (ans PointerShape, has_shape bool) {
	if len(self.pointer_shapes) > 0 {
		has_shape = true
		ans = self.pointer_shapes[len(self.pointer_shapes)-1]
	}
	return
}
