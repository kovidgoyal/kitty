// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"io"
)

var _ = fmt.Print

type StreamDecompressor = func(chunk []byte, is_last bool) error

// Wrap Go's awful decompressor routines to allow feeding them
// data in chunks. For example:
// sd, err := NewStreamDecompressor(zlib.NewReader)
// sd(chunk, false, output_callback)
// ...
// sd(last_chunk, true, output_callback)
// after this call calling sd() further will just return io.EOF
func NewStreamDecompressor(constructor func(io.Reader) (io.ReadCloser, error), output io.Writer) StreamDecompressor {
	if constructor == nil { // identity decompressor
		var err error
		return func(chunk []byte, is_last bool) error {
			if err != nil {
				return err
			}
			_, err = output.Write(chunk)
			return err
		}
	}
	pipe_r, pipe_w := io.Pipe()
	finished := make(chan error, 1)
	go func() {
		var err error
		defer func() {
			finished <- err
		}()
		var impl io.ReadCloser
		impl, err = constructor(pipe_r)
		if err != nil {
			pipe_r.CloseWithError(err)
			return
		}
		_, err = io.Copy(output, impl)
		cerr := impl.Close()
		if err == nil {
			err = cerr
		}
		pipe_r.CloseWithError(err)
	}()

	var iter_err error
	return func(chunk []byte, is_last bool) error {
		if iter_err != nil {
			return iter_err
		}
		if len(chunk) > 0 {
			_, iter_err = pipe_w.Write(chunk)
			if iter_err != nil {
				return iter_err
			}
		}
		if is_last {
			pipe_w.CloseWithError(io.EOF)
			err := <-finished
			if err != nil && err != io.EOF {
				iter_err = err
				return err
			}
			iter_err = io.EOF
			return nil
		}
		return nil
	}
}
