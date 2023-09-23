// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"errors"
	"fmt"
	"syscall"
	"unsafe"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func Fallocate_simple(fd int, size int64) (err error) {
	store := &syscall.Fstore_t{
		Flags:   syscall.F_ALLOCATEALL,
		Posmode: syscall.F_PEOFPOSMODE,
		Offset:  0,
		Length:  size,
	}

	for {
		if _, _, err = syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_PREALLOCATE, uintptr(unsafe.Pointer(store))); !errors.Is(err, unix.EINTR) {
			return err
		}
	}
}
