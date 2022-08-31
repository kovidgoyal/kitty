// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"encoding/base64"
	"errors"
	"io"
	"os"
	"strings"
)

func parse_send_text(io_data *rc_io_data, args []string) error {
	generators := make([]func(io_data *rc_io_data) (bool, error), 0, 1)

	if len(args) > 0 {
		text := strings.Join(args, " ")
		text_gen := func(io_data *rc_io_data) (bool, error) {
			limit := len(text)
			if limit > 2048 {
				limit = 2048
			}
			set_payload_data(io_data, "text:"+text[:limit])
			text = text[limit:]
			return len(text) == 0, nil
		}
		generators = append(generators, text_gen)
	}

	if options_send_text.from_file != "" {
		f, err := os.Open(options_send_text.from_file)
		if err != nil {
			return err
		}
		chunk := make([]byte, 2048)
		file_gen := func(io_data *rc_io_data) (bool, error) {
			n, err := f.Read(chunk)
			if err != nil && !errors.Is(err, io.EOF) {
				return false, err
			}
			set_payload_data(io_data, "base64:"+base64.StdEncoding.EncodeToString(chunk[:n]))
			return n == 0, nil
		}
		generators = append(generators, file_gen)
	}

	io_data.multiple_payload_generator = func(io_data *rc_io_data) (bool, error) {
		if len(generators) == 0 {
			set_payload_data(io_data, "text:")
			return true, nil
		}
		finished, err := generators[0](io_data)
		if finished {
			generators = generators[1:]
			finished = len(generators) == 0
		}
		return finished, err
	}

	return nil
}
