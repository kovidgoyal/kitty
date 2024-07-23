//go:build linux

// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>
package utils

import (
	"fmt"
	"io/fs"
	"os"
	"strconv"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func CreateAnonymousTemp(dir string, perms ...fs.FileMode) (*os.File, error) {
	if dir == "" {
		dir = os.TempDir()
	}
	var perm fs.FileMode = unix.S_IREAD | unix.S_IWRITE
	if len(perms) > 0 {
		perm = perms[0]
	}
	fd, err := unix.Open(dir, unix.O_RDWR|unix.O_TMPFILE|unix.O_CLOEXEC, uint32(perm&fs.ModePerm))

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
