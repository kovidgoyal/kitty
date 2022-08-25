// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"io"
	"time"
)

const (
	DEFAULT_IO_BUFFER_SIZE = 8192
)

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
