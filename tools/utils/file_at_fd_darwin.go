package utils

import (
	"fmt"
	"os"
	"path/filepath"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func mknodAt(parent *os.File, name string, mode uint32, dev int) (err error) {
	path := filepath.Join(parent.Name(), name)
	for {
		if err = unix.Mknod(path, mode, dev); err != unix.EINTR {
			break
		}
	}
	return
}
