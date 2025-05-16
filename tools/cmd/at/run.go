package at

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/kovidgoyal/kitty/tools/tty"
)

var _ = fmt.Print

type run_response_data struct {
	Stdout      string `json:"stdout"`
	Stderr      string `json:"stderr"`
	Exit_code   int    `json:"exit_code"`
	Exit_status int    `json:"exit_status"`
}

func run_handle_response(data []byte) error {
	var r run_response_data
	if err := json.Unmarshal(data, &r); err != nil {
		return err
	}
	if stdout, err := base64.StdEncoding.DecodeString(r.Stdout); err == nil {
		_, _ = os.Stdout.Write(stdout)
	} else {
		return err
	}
	if stderr, err := base64.StdEncoding.DecodeString(r.Stderr); err == nil {
		_, _ = os.Stderr.Write(stderr)
	} else {
		return err
	}
	if r.Exit_code != 0 {
		return &exit_error{r.Exit_code}
	}
	return nil
}

func read_run_data(io_data *rc_io_data, args []string, payload *run_json_type) (func(io_data *rc_io_data) (bool, error), error) {
	is_first_call := true
	is_tty := tty.IsTerminal(os.Stdin.Fd())
	buf := make([]byte, 4096)
	cmdline := make([]escaped_string, len(args))
	for i, s := range args {
		cmdline[i] = escaped_string(s)
	}
	payload.Cmdline = cmdline
	io_data.handle_response = run_handle_response

	return func(io_data *rc_io_data) (bool, error) {
		if is_first_call {
			is_first_call = false
		} else {
			io_data.rc.Stream = false
		}
		buf = buf[:cap(buf)]
		var n int
		var err error
		if is_tty {
			buf = buf[:0]
			err = io.EOF
		} else {
			n, err = os.Stdin.Read(buf)
			if err != nil && err != io.EOF {
				return false, err
			}
			buf = buf[:n]
		}
		set_payload_data(io_data, base64.StdEncoding.EncodeToString(buf))
		if err == io.EOF {
			return true, nil
		}
		return false, nil
	}, nil

}
