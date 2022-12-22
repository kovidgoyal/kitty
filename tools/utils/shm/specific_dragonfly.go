// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"fmt"
)

var _ = fmt.Print

// https://www.dragonflybsd.org/cgi/web-man?command=shm_open&section=3
const SHM_DIR = "/var/run/shm"
