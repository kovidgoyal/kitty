// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"fmt"
	"strconv"
	"strings"
)

func parse_scroll_amount(amt string) ([]any, error) {
	var ans = make([]any, 2)
	if amt == "start" || amt == "end" {
		ans[0] = amt
		ans[1] = nil
	} else {
		pages := strings.Contains(amt, "p")
		unscroll := strings.Contains(amt, "u")
		prompt := strings.Contains(amt, "r")
		var mult float64 = 1
		if strings.HasSuffix(amt, "-") && !unscroll {
			mult = -1
		}
		q, err := strconv.ParseFloat(strings.TrimRight(amt, "+-plur"), 64)
		if err != nil {
			return ans, err
		}
		if !pages && q != float64(int(q)) {
			return ans, fmt.Errorf("The number must be an integer")
		}
		ans[0] = q * mult
		if pages {
			ans[1] = "p"
		} else if unscroll {
			ans[1] = "u"
		} else if prompt {
			ans[1] = "r"
		} else {
			ans[1] = "l"
		}
	}
	return ans, nil
}
