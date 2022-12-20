// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"fmt"
)

var _ = fmt.Print

const SHM_DIR = "/var/shm"

func modify_pattern(pattern string) string {
	return pattern
}
