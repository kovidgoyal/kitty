// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tty

import (
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"os"
	"strconv"
	"sync"
	"time"

	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/utils"
)

const (
	TCSANOW   = 0
	TCSADRAIN = 1
	TCSAFLUSH = 2
)

type Term struct {
	os_file *os.File
	states  []unix.Termios
}

func eintr_retry_noret(f func() error) error {
	for {
		qerr := f()
		if qerr == unix.EINTR {
			continue
		}
		return qerr
	}
}

func eintr_retry_intret(f func() (int, error)) (int, error) {
	for {
		q, qerr := f()
		if qerr == unix.EINTR {
			continue
		}
		return q, qerr
	}
}

func IsTerminal(fd uintptr) bool {
	var t unix.Termios
	err := eintr_retry_noret(func() error { return Tcgetattr(int(fd), &t) })
	return err == nil
}

type TermiosOperation func(t *unix.Termios)

func get_vmin_and_vtime(d time.Duration) (uint8, uint8) {
	if d > 0 {
		// VTIME is expressed in terms of deciseconds
		vtimeDeci := d.Milliseconds() / 100
		// ensure valid range
		vtime := uint8(clamp(vtimeDeci, 1, 0xff))
		return 0, vtime
	}
	// block indefinitely until we receive at least 1 byte
	return 1, 0
}

func SetReadTimeout(d time.Duration) TermiosOperation {
	vmin, vtime := get_vmin_and_vtime(d)
	return func(t *unix.Termios) {
		t.Cc[unix.VMIN] = vmin
		t.Cc[unix.VTIME] = vtime
	}
}

var SetBlockingRead TermiosOperation = SetReadTimeout(0)

var SetNoCanonical TermiosOperation = func(t *unix.Termios) {
	t.Lflag &^= unix.ICANON
}

var SetRaw TermiosOperation = func(t *unix.Termios) {
	// This attempts to replicate the behaviour documented for cfmakeraw in
	// the termios(3) manpage, as Go doesn't wrap cfmakeraw probably because its not in POSIX
	t.Iflag &^= unix.IGNBRK | unix.BRKINT | unix.PARMRK | unix.ISTRIP | unix.INLCR | unix.IGNCR | unix.ICRNL | unix.IXON
	t.Oflag &^= unix.OPOST
	t.Lflag &^= unix.ECHO | unix.ECHONL | unix.ICANON | unix.ISIG | unix.IEXTEN
	t.Cflag &^= unix.CSIZE | unix.PARENB
	t.Cflag |= unix.CS8
	t.Cc[unix.VMIN] = 1
	t.Cc[unix.VTIME] = 0
}
var SetNoEcho TermiosOperation = func(t *unix.Termios) {
	t.Lflag &^= unix.ECHO
}

var SetReadPassword TermiosOperation = func(t *unix.Termios) {
	t.Lflag &^= unix.ECHO
	t.Lflag |= unix.ISIG
	t.Lflag &^= unix.ICANON
	t.Iflag |= unix.ICRNL
	t.Cc[unix.VMIN] = 1
	t.Cc[unix.VTIME] = 0
}

func WrapTerm(fd int, name string, operations ...TermiosOperation) (self *Term, err error) {
	if name == "" {
		name = fmt.Sprintf("<fd: %d>", fd)
	}
	os_file := os.NewFile(uintptr(fd), name)
	if os_file == nil {
		return nil, os.ErrInvalid
	}
	self = &Term{os_file: os_file}
	err = self.ApplyOperations(TCSANOW, operations...)
	if err != nil {
		self.Close()
		self = nil
	}
	return
}

func OpenTerm(name string, operations ...TermiosOperation) (self *Term, err error) {
	fd, err := eintr_retry_intret(func() (int, error) {
		return unix.Open(name, unix.O_NOCTTY|unix.O_CLOEXEC|unix.O_NDELAY|unix.O_RDWR, 0666)
	})
	if err != nil {
		return nil, &os.PathError{Op: "open", Path: name, Err: err}
	}
	self, err = WrapTerm(fd, name, operations...)
	return
}

func OpenControllingTerm(operations ...TermiosOperation) (self *Term, err error) {
	return OpenTerm(Ctermid(), operations...)
}

func (self *Term) Fd() int {
	if self.os_file == nil {
		return -1
	}
	return int(self.os_file.Fd())
}

func (self *Term) Close() error {
	if self.os_file == nil {
		return nil
	}
	err := eintr_retry_noret(func() error { return self.os_file.Close() })
	self.os_file = nil
	return err
}

func (self *Term) WasEchoOnOriginally() bool {
	if len(self.states) > 0 {
		return self.states[0].Lflag&unix.ECHO != 0
	}
	return false
}

func (self *Term) Tcgetattr(ans *unix.Termios) error {
	return eintr_retry_noret(func() error { return Tcgetattr(self.Fd(), ans) })
}

func (self *Term) Tcsetattr(when uintptr, ans *unix.Termios) error {
	return eintr_retry_noret(func() error { return Tcsetattr(self.Fd(), when, ans) })
}

func (self *Term) set_termios_attrs(when uintptr, modify func(*unix.Termios)) (err error) {
	var state unix.Termios
	if err = self.Tcgetattr(&state); err != nil {
		return
	}
	new_state := state
	modify(&new_state)
	if err = self.Tcsetattr(when, &new_state); err == nil {
		self.states = append(self.states, state)
	}
	return
}

func (self *Term) ApplyOperations(when uintptr, operations ...TermiosOperation) (err error) {
	if len(operations) == 0 {
		return
	}
	return self.set_termios_attrs(when, func(t *unix.Termios) {
		for _, op := range operations {
			op(t)
		}
	})
}

func (self *Term) PopStateWhen(when uintptr) (err error) {
	if len(self.states) == 0 {
		return nil
	}
	idx := len(self.states) - 1
	if err = self.Tcsetattr(when, &self.states[idx]); err == nil {
		self.states = self.states[:idx]
	}
	return
}

func (self *Term) PopState() error {
	return self.PopStateWhen(TCSAFLUSH)
}

func (self *Term) RestoreWhen(when uintptr) (err error) {
	if len(self.states) == 0 {
		return nil
	}
	self.states = self.states[:1]
	return self.PopStateWhen(when)
}

func (self *Term) Restore() error {
	return self.RestoreWhen(TCSAFLUSH)
}

func (self *Term) RestoreAndClose() error {
	_ = self.Restore()
	return self.Close()
}

func (self *Term) Suspend() (resume func() error, err error) {
	var state unix.Termios
	err = self.Tcgetattr(&state)
	if err != nil {
		return nil, err
	}
	if len(self.states) > 0 {
		err := self.Tcsetattr(TCSANOW, &self.states[0])
		if err != nil {
			return nil, err
		}
	}
	return func() error { return self.Tcsetattr(TCSANOW, &state) }, nil

}

func (self *Term) SuspendAndRun(callback func() error) error {
	resume, err := self.Suspend()
	if err != nil {
		return err
	}
	err = callback()
	if rerr := resume(); rerr != nil {
		err = rerr
	}
	return err
}

func clamp(v, lo, hi int64) int64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func (self *Term) ReadWithTimeout(b []byte, d time.Duration) (n int, err error) {
	var read, write, in_err unix.FdSet
	pselect := func() (int, error) {
		read.Zero()
		write.Zero()
		in_err.Zero()
		read.Set(self.Fd())
		return utils.Select(self.Fd()+1, &read, &write, &in_err, d)
	}
	num_ready, err := pselect()
	if err != nil {
		return 0, err
	}
	if num_ready == 0 {
		err = os.ErrDeadlineExceeded
		return 0, err
	}
	for {
		n, err = self.Read(b)
		if errors.Is(err, unix.EINTR) {
			continue
		}
		return n, err
	}
}

func is_temporary_read_error(err error) bool {
	return errors.Is(err, unix.EINTR) || errors.Is(err, unix.EAGAIN) || errors.Is(err, unix.EWOULDBLOCK)
}

func (self *Term) Read(b []byte) (n int, err error) {
	for {
		n, err = self.os_file.Read(b)
		// On macOS we get EAGAIN if another thread is writing to the tty at the same time
		if err != nil && is_temporary_read_error(err) && n <= 0 {
			continue
		}
		return
	}
}

func (self *Term) Write(b []byte) (int, error) {
	return self.os_file.Write(b)
}

func is_temporary_error(err error) bool {
	return errors.Is(err, unix.EINTR) || errors.Is(err, unix.EAGAIN) || errors.Is(err, unix.EWOULDBLOCK) || errors.Is(err, io.ErrShortWrite)
}

func (self *Term) WriteAll(b []byte) error {
	for len(b) > 0 {
		n, err := self.os_file.Write(b)
		if err != nil && !is_temporary_error(err) {
			return err
		}
		b = b[n:]
	}
	return nil
}

func (self *Term) WriteAllString(s string) error {
	return self.WriteAll(utils.UnsafeStringToBytes(s))
}

func (self *Term) WriteString(b string) (int, error) {
	return self.os_file.WriteString(b)
}

func (self *Term) DebugPrintln(a ...any) {
	msg := fmt.Appendln(nil, a...)
	const limit = 2048
	encoded := make([]byte, limit*2)
	for i := 0; i < len(msg); i += limit {
		end := min(i+limit, len(msg))
		chunk := msg[i:end]
		encoded = encoded[:cap(encoded)]
		base64.StdEncoding.Encode(encoded, chunk)
		_, _ = self.WriteString("\x1bP@kitty-print|")
		_, _ = self.Write(encoded)
		_, _ = self.WriteString("\x1b\\")
	}
}

func GetSize(fd int) (*unix.Winsize, error) {
	for {
		sz, err := unix.IoctlGetWinsize(fd, unix.TIOCGWINSZ)
		if err != unix.EINTR {
			return sz, err
		}
	}
}

func (self *Term) GetSize() (*unix.Winsize, error) {
	return GetSize(self.Fd())
}

// go doesn't have a wrapper for ctermid()
func Ctermid() string { return "/dev/tty" }

var KittyStdout = sync.OnceValue(func() *os.File {
	if fds := os.Getenv(`KITTY_STDIO_FORWARDED`); fds != "" {
		if fd, err := strconv.Atoi(fds); err == nil && fd > -1 {
			if f := os.NewFile(uintptr(fd), "<kitty_stdout>"); f != nil {
				return f
			}
		}
	}
	return nil
})

func DebugPrintln(a ...any) {
	if f := KittyStdout(); f != nil {
		fmt.Fprintln(f, a...)
		return
	}
	term, err := OpenControllingTerm()
	if err == nil {
		defer term.Close()
		term.DebugPrintln(a...)
	}
}

func ReadSingleByteFromTerminal() (b byte, err error) {
	term, err := OpenControllingTerm(SetBlockingRead, SetNoCanonical)
	if err != nil {
		return 0, err
	}
	defer term.Close()
	ans := []byte{b}
	for {
		n, err := term.Read(ans)
		if err != nil {
			return 0, err
		}
		if n > 0 {
			return ans[0], nil
		}
	}
}
