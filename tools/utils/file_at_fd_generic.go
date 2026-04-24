//go:build !darwin

package utils

import (
	"fmt"
	"os"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func mknodAt(parent *os.File, name string, mode uint32, dev int) (err error) {
	for {
		if err = unix.Mknodat(int(parent.Fd()), name, mode, dev); err != unix.EINTR {
			break
		}
	}
	return
}
