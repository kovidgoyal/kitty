// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

//go:build !linux

package shm

import (
	"errors"
	"fmt"
)

var _ = fmt.Print

func Fallocate_simple(fd int, size int64) (err error) {
	return errors.ErrUnsupported
}
