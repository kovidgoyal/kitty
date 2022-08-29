// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"kitty/tools/utils"
)

func parse_key_val_args(args []string) map[string]string {
	ans := make(map[string]string, len(args))
	for _, arg := range args {
		key, value, found := utils.Cut(arg, "=")
		if found {
			ans[key] = value
		} else {
			ans[key+"="] = ""
		}
	}
	return ans
}
