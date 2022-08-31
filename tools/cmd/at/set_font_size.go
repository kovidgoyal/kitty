// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"strconv"
)

func parse_set_font_size(arg string, payload *set_font_size_json_type) error {
	if len(arg) > 0 && (arg[0] == '+' || arg[0] == '-') {
		payload.Increment_op = arg[:1]
		arg = arg[1:]
	}
	val, err := strconv.ParseFloat(arg, 64)
	if err != nil {
		return err
	}
	payload.Size = val
	return nil
}
