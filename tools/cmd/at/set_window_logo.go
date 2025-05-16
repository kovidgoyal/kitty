// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"image"
	"io"
	"os"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils/images"
)

func set_payload_data(io_data *rc_io_data, data string) {
	set_payload_string_field(io_data, "Data", data)
}

func read_window_logo(io_data *rc_io_data, path string) (func(io_data *rc_io_data) (bool, error), error) {
	if strings.ToLower(path) == "none" {
		io_data.rc.Stream = false
		return func(io_data *rc_io_data) (bool, error) {
			set_payload_data(io_data, "-")
			return true, nil
		}, nil
	}

	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	var image_data_stream io.Reader
	image_data_stream = f
	config, format, ierr := image.DecodeConfig(f)
	if ierr != nil {
		return nil, fmt.Errorf("%s is not a supported image format", path)
	}
	f.Seek(0, 0)

	if format != "png" {
		f.Seek(0, 0)
		img, _, err := image.Decode(f)
		if err != nil {
			f.Close()
		}
		f.Close()
		b := bytes.Buffer{}
		b.Grow(config.Height * config.Width * 4)
		err = images.Encode(&b, img, "image/png")
		if err != nil {
			return nil, err
		}
		image_data_stream = &b
	}
	is_first_call := true
	buf := make([]byte, 2048)

	return func(io_data *rc_io_data) (bool, error) {
		if is_first_call {
			is_first_call = false
		} else {
			io_data.rc.Stream = false
		}
		buf = buf[:cap(buf)]
		n, err := image_data_stream.Read(buf)
		if err != nil && err != io.EOF {
			return false, err
		}
		buf = buf[:n]
		set_payload_data(io_data, base64.StdEncoding.EncodeToString(buf))
		if err == io.EOF {
			return true, nil
		}
		return false, nil
	}, nil
}
