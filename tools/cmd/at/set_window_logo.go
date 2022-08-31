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

func read_window_logo(path string) (func(io_data *rc_io_data) (bool, error), error) {
	if strings.ToLower(path) == "none" {
		return func(io_data *rc_io_data) (bool, error) {
			io_data.rc.Payload = "-"
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

	return func(io_data *rc_io_data) (bool, error) {
		payload := io_data.rc.Payload.(set_window_logo_json_type)
		if len(buf) == 0 {
			payload.Data = ""
			io_data.rc.Payload = payload
			return true, nil
		}
		payload.Data = base64.StdEncoding.EncodeToString(buf)
		io_data.rc.Payload = payload
		buf = buf[:cap(buf)]
		n, err := f.Read(buf)
		if err != nil && err != io.EOF {
			return false, err
		}
		buf = buf[:n]
		return false, nil
	}, nil
}
