package utils

import (
	"fmt"
	"os"
	"path/filepath"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func mknodAt(parent *os.File, name string, mode uint32, dev uint64) (err error) {
	for {
		if err = unix.Mknodat(int(parent.Fd()), name, mode, int(dev)); err != unix.EINTR {
			break
		}
	}
	return
}

func readLinkAt(parent *os.File, name string, buf []byte) (n int, err error) {
	path := filepath.Join(parent.Name(), name)
	for {
		if n, err = unix.Readlink(path, buf[:]); err != unix.EINTR {
			break
		}
	}
	return
}

