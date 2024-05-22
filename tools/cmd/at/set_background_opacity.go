// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import "strconv"

func parse_opacity(arg string) (float64, error) {
	ans, err := strconv.ParseFloat(arg, 64)
	if err != nil {
		return 0, nil
	}
	return max(0, min(ans, 1)), nil
}
