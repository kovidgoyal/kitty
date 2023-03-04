// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"fmt"
	"strings"
)

var valid_color_names = map[string]bool{"active_fg": true, "active_bg": true, "inactive_fg": true, "inactive_bg": true}

func parse_tab_colors(args []string) (map[string]any, error) {
	ans := make(map[string]any, len(args))
	for _, arg := range args {
		key, val, found := strings.Cut(strings.ToLower(arg), "=")
		if !found {
			return nil, fmt.Errorf("%s is not a valid setting", arg)
		}
		if !valid_color_names[key] {
			return nil, fmt.Errorf("%s is not a valid color name", key)
		}
		err := set_color_in_color_map(key, val, ans, false, false)
		if err != nil {
			return nil, err
		}
	}
	return ans, nil
}
