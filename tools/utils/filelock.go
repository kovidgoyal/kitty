// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"errors"
	"fmt"
	"io/fs"
	"os"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func lock(fd, op int, path string) (err error) {
	for {
		err = unix.Flock(fd, op)
		if !errors.Is(err, unix.EINTR) {
			break
		}
	}
	if err != nil {
		opname := "exclusive flock()"
		switch op {
		case unix.LOCK_UN:
			opname = "unlock flock()"
		case unix.LOCK_SH:
			opname = "shared flock()"
		}
		return &fs.PathError{
			Op:   opname,
			Path: path,
			Err:  err,
		}
	}
	return nil
}

func LockFileShared(f *os.File) error {
	return lock(int(f.Fd()), unix.LOCK_SH, f.Name())
}

func LockFileExclusive(f *os.File) error {
	return lock(int(f.Fd()), unix.LOCK_EX, f.Name())
}

func UnlockFile(f *os.File) error {
	return lock(int(f.Fd()), unix.LOCK_UN, f.Name())
}
