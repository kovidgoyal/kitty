// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"encoding/base64"
	"errors"
	"io"
	"os"
	"strings"
)

type generator_function func(io_data *rc_io_data) (bool, error)

func parse_send_text(io_data *rc_io_data, args []string) error {
	generators := make([]generator_function, 0, 1)

	if len(args) > 0 {
		text := strings.Join(args, " ")
		text_gen := func(io_data *rc_io_data) (bool, error) {
			payload := io_data.rc.Payload.(send_text_json_type)
			payload.Data = "text:" + text[:2048]
			io_data.rc.Payload = payload
			text = text[2048:]
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
			payload := io_data.rc.Payload.(send_text_json_type)
			payload.Data = "base64:" + base64.StdEncoding.EncodeToString(chunk[:n])
			io_data.rc.Payload = payload
			return n == 0, nil
		}
		generators = append(generators, file_gen)
	}

	io_data.multiple_payload_generator = func(io_data *rc_io_data) (bool, error) {
		if len(generators) == 0 {
			payload := io_data.rc.Payload.(send_text_json_type)
			payload.Data = "text:"
			io_data.rc.Payload = payload
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
