package utils

import (
	"io"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

const (
	DEFAULT_IO_BUFFER_SIZE = 8192
)

func NsecToTimespec(d time.Duration) unix.Timespec {
	nv := syscall.NsecToTimespec(int64(d))
	return unix.Timespec{Sec: nv.Sec, Nsec: nv.Nsec}
}

func NsecToTimeval(d time.Duration) unix.Timeval {
	nv := syscall.NsecToTimeval(int64(d))
	return unix.Timeval{Sec: nv.Sec, Usec: nv.Usec}
}

type BytesReader struct {
	Data []byte
}

type Reader interface {
	ReadWithTimeout(b []byte, timeout time.Duration) (n int, err error)
	GetBuf() []byte
}

func (self *BytesReader) Read(b []byte) (n int, err error) {
	if len(self.Data) == 0 {
		return 0, io.EOF
	}
	n = copy(b, self.Data)
	self.Data = self.Data[n:]
	return
}

func (self *BytesReader) ReadWithTimeout(b []byte, timeout time.Duration) (n int, err error) {
	return self.Read(b)
}

func (self *BytesReader) GetBuf() (ans []byte) {
	ans = self.Data
	self.Data = make([]byte, 0)
	return
}
