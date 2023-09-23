// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

//go:build !linux

package shm

import (
	"fmt"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func Fallocate_simple(fd int, size int64) (err error) {
	return unix.ENOSYS
}
