//go:build linux

// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>
package utils

import (
	"fmt"
	"os"
	"strconv"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func CreateAnonymousTemp(dir string) (*os.File, error) {
	if dir == "" {
		dir = os.TempDir()
	}
	fd, err := unix.Open(dir, unix.O_RDWR|unix.O_TMPFILE|unix.O_CLOEXEC, 0600)

	if err == nil {
		path := "/proc/self/fd/" + strconv.FormatUint(uint64(fd), 10)
		return os.NewFile(uintptr(fd), path), nil
	}
	if err == unix.ENOENT {
		return nil, &os.PathError{
			Op:   "open",
			Path: dir,
			Err:  err,
		}
	}
	f, err := os.CreateTemp(dir, "")
	if err != nil {
		return nil, err
	}
	err = os.Remove(f.Name())
	if err != nil {
		f.Close()
		return nil, err
	}
	return f, err
}
