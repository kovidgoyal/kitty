// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"fmt"
	"os"

	"github.com/emmansun/base64"
)

func screenshot_handle_response(data []byte) error {
	png_data, err := base64.StdEncoding.DecodeString(string(data))
	if err != nil {
		return err
	}
	_, err = os.Stdout.Write(png_data)
	return err
}

func read_screenshot_args(io_data *rc_io_data, args []string) (func(io_data *rc_io_data) (bool, error), error) {
	if len(args) > 1 {
		return nil, fmt.Errorf("%s", "Must specify at most one output file")
	}
	if len(args) == 0 {
		// kitty writes the screenshot directly to the output file when one is
		// given (it runs on the same computer as kitty), so a custom response
		// handler is only needed to write the PNG data to STDOUT.
		io_data.handle_response = screenshot_handle_response
	}
	return func(io_data *rc_io_data) (bool, error) {
		// io_data.rc.Payload is only populated after this generator is created,
		// so the payload field must be set here rather than above.
		if len(args) == 1 {
			set_payload_string_field(io_data, "Output_path", args[0])
		}
		return true, nil
	}, nil
}
