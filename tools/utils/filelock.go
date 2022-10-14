// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"io/fs"
	"os"
	"syscall"
)

var _ = fmt.Print

func lock(fd, op int, path string) (err error) {
	for {
		err = syscall.Flock(fd, op)
		if err != syscall.EINTR {
			break
		}
	}
	if err != nil {
		opname := "exclusive flock()"
		switch op {
		case syscall.LOCK_UN:
			opname = "unlock flock()"
		case syscall.LOCK_SH:
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
	return lock(int(f.Fd()), syscall.LOCK_SH, f.Name())
}

func LockFileExclusive(f *os.File) error {
	return lock(int(f.Fd()), syscall.LOCK_EX, f.Name())
}

func UnlockFile(f *os.File) error {
	return lock(int(f.Fd()), syscall.LOCK_UN, f.Name())
}
