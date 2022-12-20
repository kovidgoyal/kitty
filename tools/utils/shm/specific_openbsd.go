// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"fmt"
)

var _ = fmt.Print

const SHM_DIR = "/tmp"

func modify_pattern(pattern string) string {
	// https://github.com/openbsd/src/blob/master/lib/libc/gen/shm_open.c
	if strings.Contains(pattern, "*") {
		pattern += ".shm"
	} else {
		pattern += "*.shm"
	}
	return pattern
}
