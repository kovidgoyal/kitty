// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"fmt"
	"strconv"
	"strings"
)

func parse_set_spacing(args []string) (map[string]any, error) {
	ans := make(map[string]any, len(args))
	mapper := make(map[string][]string, 32)
	types := [2]string{"margin", "padding"}
	for _, q := range types {
		mapper[q] = []string{q + "-left", q + "-top", q + "-right", q + "-bottom"}
		mapper[q+"-h"] = []string{q + "-left", q + "-right"}
		mapper[q+"-v"] = []string{q + "-top", q + "-bottom"}
		mapper[q+"-left"] = []string{q + "-left"}
		mapper[q+"-right"] = []string{q + "-right"}
		mapper[q+"-top"] = []string{q + "-top"}
		mapper[q+"-bottom"] = []string{q + "-bottom"}
	}
	for _, arg := range args {
		k, v, found := strings.Cut(arg, "=")
		if !found {
			return nil, fmt.Errorf("%s is not a valid setting", arg)
		}
		k = strings.ToLower(k)
		v = strings.ToLower(v)
		which, found := mapper[k]
		if !found {
			return nil, fmt.Errorf("%s is not a valid edge specification", k)
		}
		if v == "default" {
			for _, q := range which {
				ans[q] = nil
			}
		} else {
			val, err := strconv.ParseFloat(v, 64)
			if err != nil {
				return nil, fmt.Errorf("%s is not a number", v)
			}
			for _, q := range which {
				ans[q] = val
			}
		}

	}
	return ans, nil
}
