package utils

import (
	"errors"
	"github.com/pkg/term/termios"
	"golang.org/x/sys/unix"
	"io"
	"os"
	"syscall"
	"time"
)

type Term struct {
	name   string
	fd     int
	states []unix.Termios
}

func OpenTerm(name string, in_raw_mode bool) (self *Term, err error) {
	fd, err := unix.Open(name, unix.O_NOCTTY|unix.O_CLOEXEC|unix.O_NDELAY|unix.O_RDWR, 0666)
	if err != nil {
		return nil, &os.PathError{Op: "open", Path: name, Err: err}
	}

	self = &Term{name: name, fd: fd}
	err = unix.SetNonblock(self.fd, false)
	if err != nil {
		return
	}
	if in_raw_mode {
		err = self.SetRaw()
		if err != nil {
			return
		}
	}
	return
}

func OpenControllingTerm(in_raw_mode bool) (self *Term, err error) {
	return OpenTerm("/dev/tty", in_raw_mode) // go doesnt have a wrapper for ctermid()
}

func (self *Term) Fd() int { return self.fd }

func (self *Term) Close() error {
	err := unix.Close(self.fd)
	self.fd = -1
	return err
}

func (self *Term) SetRawWhen(when uintptr) (err error) {
	var state unix.Termios
	if err = termios.Tcgetattr(uintptr(self.fd), &state); err != nil {
		return
	}
	new_state := state
	termios.Cfmakeraw(&new_state)
	err = termios.Tcsetattr(uintptr(self.fd), when, &new_state)
	if err != nil {
		self.states = append(self.states, state)
	}
	return
}

func (self *Term) SetRaw() error {
	return self.SetRawWhen(termios.TCSANOW)
}

func (self *Term) PopStateWhen(when uintptr) (err error) {
	if len(self.states) == 0 {
		return nil
	}
	idx := len(self.states) - 1
	err = termios.Tcsetattr(uintptr(self.fd), when, &self.states[idx])
	if err != nil {
		self.states = self.states[:idx]
	}
	return
}

func (self *Term) PopState() error {
	return self.PopStateWhen(termios.TCIOFLUSH)
}

func (self *Term) RestoreWhen(when uintptr) (err error) {
	if len(self.states) == 0 {
		return nil
	}
	self.states = self.states[:1]
	return self.PopStateWhen(when)
}

func (self *Term) Restore() error {
	return self.RestoreWhen(termios.TCIOFLUSH)
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

func (self *Term) SetReadTimeout(d time.Duration) (err error) {
	var a unix.Termios
	if err := termios.Tcgetattr(uintptr(self.fd), &a); err != nil {
		return err
	}
	b := a
	b.Cc[unix.VMIN], b.Cc[unix.VTIME] = get_vmin_and_vtime(d)
	err = termios.Tcsetattr(uintptr(self.fd), termios.TCSANOW, &b)
	if err != nil {
		self.states = append(self.states, a)
	}
	return
}

func (self *Term) ReadWithTimeout(b []byte, d time.Duration) (n int, err error) {
	var read, write, in_err unix.FdSet
	tv := NsecToTimeval(d)
	read.Set(self.fd)
	num_ready, err := unix.Select(self.fd, &read, &write, &in_err, &tv)
	if err != nil {
		return
	}
	if num_ready == 0 {
		err = os.ErrDeadlineExceeded
		return
	}

	return self.Read(b)
}

func (t *Term) Read(b []byte) (int, error) {
	n, e := unix.Read(t.fd, b)
	if n < 0 {
		n = 0
	}
	if n == 0 && len(b) > 0 && e == nil {
		return 0, io.EOF
	}
	if e != nil {
		return n, &os.PathError{Op: "read", Path: t.name, Err: e}
	}
	return n, nil
}

func (t *Term) Write(b []byte) (int, error) {
	n, e := unix.Write(t.fd, b)
	if n < 0 {
		n = 0
	}
	if n != len(b) {
		return n, io.ErrShortWrite
	}
	if e != nil {
		return n, &os.PathError{Op: "write", Path: t.name, Err: e}
	}
	return n, nil
}

func NsecToTimeval(d time.Duration) unix.Timeval {
	nv := syscall.NsecToTimeval(int64(d))
	return unix.Timeval{Sec: nv.Sec, Usec: nv.Usec}
}

func (self *Term) WriteAllWithTimeout(b []byte, d time.Duration) (n int, err error) {
	var read, write, in_err unix.FdSet
	var num_ready int
	n = len(b)
	for {
		if len(b) == 0 {
			return
		}
		sysnv := NsecToTimeval(d)
		read.Zero()
		write.Zero()
		in_err.Zero()
		write.Set(self.fd)
		num_ready, err = unix.Select(self.fd, &read, &write, &in_err, &sysnv)
		if err != nil {
			n -= len(b)
			return
		}
		if num_ready == 0 {
			err = os.ErrDeadlineExceeded
			n -= len(b)
			return
		}
		num_written, werr := self.Write(b)
		if werr == nil {
			n -= len(b)
			return
		}
		if errors.Is(werr, io.ErrShortWrite) {
			b = b[num_written:]
			continue
		}
		err = werr
		n -= len(b)
		return
	}
}

func (self *Term) WriteFromReader(r Reader, read_timeout time.Duration, write_timeout time.Duration) (n int, err error) {
	buf := r.GetBuf()
	var rn, wn int
	var rerr error
	for {
		if len(buf) == 0 {
			rn, rerr = r.ReadWithTimeout(buf, read_timeout)
			if rerr != nil && !errors.Is(rerr, io.EOF) {
				err = rerr
				return
			}
			if rn == 0 {
				return n, nil
			}
		}
		wn, err = self.WriteAllWithTimeout(buf, write_timeout)
		n += wn
		if err != nil {
			return
		}

	}
}
