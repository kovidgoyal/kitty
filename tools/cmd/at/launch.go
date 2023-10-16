// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"fmt"
	"os"
)

var _ = fmt.Print

func copy_local_env(copy_env bool) []string {
	if copy_env {
		return os.Environ()
	}
	return nil
}
