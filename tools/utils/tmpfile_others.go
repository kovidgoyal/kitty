//go:build !linux

// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"io/fs"
	"os"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func CreateAnonymousTemp(dir string, perms ...fs.FileMode) (*os.File, error) {
	var perm fs.FileMode = unix.S_IREAD | unix.S_IWRITE
	default_perm := perm
	if len(perms) > 0 {
		perm = perms[0]
	}

	f, err := os.CreateTemp(dir, "")
	if err != nil {
		return nil, err
	}
	if perm != default_perm {
		err = f.Chmod(perm & fs.ModePerm)
		if err != nil {
			os.Remove(f.Name())
			f.Close()
			return nil, err
		}
	}
	err = os.Remove(f.Name())
	if err != nil {
		f.Close()
		return nil, err
	}
	return f, err
}
