// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"encoding/json"
	"fmt"
	"os"

	"kitty/tools/cli"
	"kitty/tools/utils"

	"github.com/jamesruan/go-rfc1924/base85"
)

var _ = fmt.Print

func KittenOutputSerializer() func(any) (string, error) {
	write_with_escape_code := os.Getenv("KITTEN_RUNNING_AS_UI") != ""
	os.Unsetenv("KITTEN_RUNNING_AS_UI")
	if write_with_escape_code {
		return func(what any) (string, error) {
			data, err := json.Marshal(what)
			if err != nil {
				return "", err
			}
			return "\x1bP@kitty-kitten-result|" + base85.EncodeToString(data) + "\x1b\\", nil
		}
	}
	return func(what any) (string, error) {
		if sval, ok := what.(string); ok {
			return sval, nil
		}
		data, err := json.MarshalIndent(what, "", "  ")
		if err != nil {
			return "", err
		}
		return utils.UnsafeBytesToString(data), nil
	}
}

func ReportError(err error) {
	cli.ShowError(err)
	os.Stdout.WriteString("\x1bP@kitty-overlay-ready|\x1b\\")
	HoldTillEnter(false)
}
