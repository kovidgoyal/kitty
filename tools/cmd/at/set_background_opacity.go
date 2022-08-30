// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import "strconv"

func parse_opacity(arg string) (float64, error) {
	ans, err := strconv.ParseFloat(arg, 64)
	if err != nil {
		return 0, nil
	}
	if ans < 0.1 {
		ans = 0.1
	}
	if ans > 1 {
		ans = 1
	}
	return ans, nil
}
