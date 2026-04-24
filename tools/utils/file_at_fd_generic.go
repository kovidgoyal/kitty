//go:build !darwin && !freebsd && !dragonfly

package utils

import (
	"fmt"
	"os"

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
	for {
		if n, err = unix.Readlinkat(int(parent.Fd()), name, buf[:]); err != unix.EINTR {
			break
		}
	}
	return
}
