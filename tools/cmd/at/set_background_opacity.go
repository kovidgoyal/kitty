// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"fmt"
	"math"
	"strconv"
)

func parse_opacity(arg string) (float64, error) {
	ans, err := strconv.ParseFloat(arg, 64)
	if err != nil || math.IsNaN(ans) {
		return 0, fmt.Errorf("Invalid opacity %#v: must be a number between 0 and 1", arg)
	}
	return max(0, min(ans, 1)), nil
}
