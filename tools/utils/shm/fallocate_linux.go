// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"errors"
	"fmt"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func Fallocate_simple(fd int, size int64) (err error) {
	for {
		if err = unix.Fallocate(fd, 0, 0, size); !errors.Is(err, unix.EINTR) {
			return
		}
	}
}
