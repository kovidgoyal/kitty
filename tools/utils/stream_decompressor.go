// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"errors"
	"fmt"
	"io"
)

var _ = fmt.Print

type StreamDecompressor = func(chunk []byte, is_last bool) error

type pipe_reader struct {
	pr *io.PipeReader
}

func (self *pipe_reader) Read(b []byte) (n int, err error) {
	// ensure the decompressor code never gets a zero byte read with no error
	for len(b) > 0 {
		n, err = self.pr.Read(b)
		if err != nil || n > 0 {
			return
		}
	}
	return
}

// Wrap Go's awful decompressor routines to allow feeding them
// data in chunks. For example:
// sd := NewStreamDecompressor(zlib.NewReader, output)
// sd(chunk, false)
// ...
// sd(last_chunk, true)
// after this call, calling sd() further will just return io.EOF.
// To close the decompressor at any time, call sd(nil, true).
// Note: output.Write() may be called from a different thread, but only while the main thread is in sd()
func NewStreamDecompressor(constructor func(io.Reader) (io.ReadCloser, error), output io.Writer) StreamDecompressor {
	if constructor == nil { // identity decompressor
		var err error
		return func(chunk []byte, is_last bool) error {
			if err != nil {
				return err
			}
			if len(chunk) > 0 {
				_, err = output.Write(chunk)
			}
			if is_last {
				if err == nil {
					err = io.EOF
					return nil
				}
			}
			return err
		}
	}
	pipe_r, pipe_w := io.Pipe()
	pr := pipe_reader{pr: pipe_r}
	finished := make(chan error, 1)
	finished_err := errors.New("finished")
	go func() {
		var err error
		defer func() {
			finished <- err
		}()
		var impl io.ReadCloser
		impl, err = constructor(&pr)
		if err != nil {
			pipe_r.CloseWithError(err)
			return
		}
		_, err = io.Copy(output, impl)
		cerr := impl.Close()
		if err == nil {
			err = cerr
		}
		if err == nil {
			err = finished_err
		}
		pipe_r.CloseWithError(err)
	}()

	var iter_err error
	return func(chunk []byte, is_last bool) error {
		if iter_err != nil {
			if iter_err == finished_err {
				iter_err = io.EOF
			}
			return iter_err
		}
		if len(chunk) > 0 {
			var n int
			n, iter_err = pipe_w.Write(chunk)
			if iter_err != nil && iter_err != finished_err {
				return iter_err
			}
			if n < len(chunk) {
				iter_err = io.ErrShortWrite
				return iter_err
			}
			// wait for output to finish
			if iter_err == nil {
				// after a zero byte read, pipe_reader.Read() calls pipe_r.Read() again so
				// we know it is either blocked waiting for a write to pipe_w or has finished
				_, iter_err = pipe_w.Write(nil)
				if iter_err != nil && iter_err != finished_err {
					return iter_err
				}
			}
		}
		if is_last {
			pipe_w.CloseWithError(io.EOF)
			err := <-finished
			if err != nil && err != io.EOF && err != finished_err {
				iter_err = err
				return err
			}
			iter_err = io.EOF
			return nil
		}
		return nil
	}
}
