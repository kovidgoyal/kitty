// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
)

type struct_with_data interface {
	SetData(data string)
}

func set_payload_data(io_data *rc_io_data, data string) {
	set_payload_string_field(io_data, "Data", data)
}

func read_window_logo(path string) (func(io_data *rc_io_data) (bool, error), error) {
	if strings.ToLower(path) == "none" {
		return func(io_data *rc_io_data) (bool, error) {
			set_payload_data(io_data, "-")
			return true, nil
		}, nil
	}

	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	buf := make([]byte, 2048)
	n, err := f.Read(buf)
	if err != nil && err != io.EOF {
		f.Close()
		return nil, err
	}
	buf = buf[:n]

	if http.DetectContentType(buf) != "image/png" {
		f.Close()
		return nil, fmt.Errorf("%s is not a PNG image", path)
	}
	is_first_call := true

	return func(io_data *rc_io_data) (bool, error) {
		if is_first_call {
			is_first_call = false
		} else {
			io_data.rc.Stream = false
		}
		if len(buf) == 0 {
			set_payload_data(io_data, "")
			io_data.rc.Stream = false
			return true, nil
		}
		set_payload_data(io_data, base64.StdEncoding.EncodeToString(buf))
		buf = buf[:cap(buf)]
		n, err := f.Read(buf)
		if err != nil && err != io.EOF {
			return false, err
		}
		buf = buf[:n]
		return false, nil
	}, nil
}
