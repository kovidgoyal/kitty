// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"io"
)

var _ = fmt.Print

// Decompress the data in chunk. output_callback() will be called zero or more times with decompressed data. Note that
// it may be called in a different goroutine. The data provided to output_callback() is only valid for the lifetime of
// output_callback(), so it should copy out the data.
type StreamDecompressor = func(chunk []byte, is_last bool, output_callback func([]byte) error) error

type output struct {
	chunk []byte
	err   error
}

type stream_decompressor struct {
	impl     io.ReadCloser
	pipe_r   *io.PipeReader
	pipe_w   *io.PipeWriter
	obuf     [8192]byte
	err      error
	callback func([]byte) error
}

func (self *stream_decompressor) process() {
	for {
		n, err := self.impl.Read(self.obuf[:])
		if n > 0 {
			if ocerr := self.callback(self.obuf[:n]); ocerr != nil {
				self.pipe_r.CloseWithError(ocerr)
				break
			}
		}
		if err != nil {
			self.pipe_r.CloseWithError(err)
			break
		}
	}
}

func (self *stream_decompressor) next(chunk []byte, is_last bool, output_callback func([]byte) error) (err error) {
	if self.err != nil {
		return self.err
	}
	self.callback = output_callback
	if _, err = self.pipe_w.Write(chunk); err != nil {
		self.err = err
		return err
	}
	if is_last {
		defer func() {
			self.pipe_r.Close()
			self.pipe_w.Close()
			if self.err == nil {
				self.err = io.EOF
			}
		}()
		self.err = self.impl.Close()
		return self.err
	}
	return nil
}

// Wrap Go's awful decompressor routines to allow feeding them
// data in chunks. For example:
// sd, err := NewStreamDecompressor(zlib.NewReader)
// sd(chunk, false, output_callback)
// ...
// sd(last_chunk, true, output_callback)
// after this call calling sd() further will just return io.EOF
func NewStreamDecompressor(constructor func(io.Reader) (io.ReadCloser, error)) (StreamDecompressor, error) {
	if constructor == nil { // identity decompressor
		var err error
		return func(chunk []byte, is_last bool, cb func([]byte) error) error {
			if err != nil {
				return err
			}
			err = cb(chunk)
			retval := err
			if is_last && err != nil {
				err = io.EOF
			}
			return retval
		}, nil
	}
	s := stream_decompressor{}
	s.pipe_r, s.pipe_w = io.Pipe()
	rc, err := constructor(s.pipe_r)
	if err != nil {
		return nil, err
	}
	s.impl = rc
	go s.process()
	return s.next, nil
}
