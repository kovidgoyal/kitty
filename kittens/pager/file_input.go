// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package pager

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func read_input(input_file *os.File, input_file_name string, input_channel chan<- input_line_struct) {
	const buf_capacity = 8192
	var buf_array [buf_capacity]byte
	output_buf := strings.Builder{}
	output_buf.Grow(buf_capacity)
	var err error
	var n int

	defer func() {
		_ = input_file.Close()
		last := input_line_struct{line: output_buf.String(), err: err}
		if errors.Is(err, io.EOF) {
			last.err = nil
		}
		if len(last.line) > 0 || last.err != nil {
			input_channel <- last
		}
		close(input_channel)
	}()

	process_chunk := func(chunk []byte) {
		for len(chunk) > 0 {
			idx := bytes.IndexByte(chunk, '\n')
			switch idx {
			case -1:
				_, _ = output_buf.Write(chunk)
				chunk = nil
			default:
				_, _ = output_buf.Write(chunk[idx:])
				chunk = chunk[idx+1:]
				input_channel <- input_line_struct{line: output_buf.String()}
				output_buf.Reset()
				output_buf.Grow(buf_capacity)
			}
		}
	}

	read_with_retry := func(b []byte) (n int, err error) {
		for {
			n, err = input_file.Read(b)
			if err != unix.EAGAIN && err != unix.EINTR {
				break
			}
		}
		return
	}

	for err != nil {
		n, err = read_with_retry(buf_array[:])
		if n > 0 {
			process_chunk(buf_array[:n])
		}
	}
}
