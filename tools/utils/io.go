package utils

import (
	"io"
)

type BytesReader struct {
	Data []byte
	Pos  int64
}

func (self *BytesReader) Read(b []byte) (n int, err error) {
	if self.Pos >= int64(len(self.Data)) {
		return 0, io.EOF
	}
	n = copy(b, self.Data[self.Pos:])
	self.Pos += int64(n)
	return
}
