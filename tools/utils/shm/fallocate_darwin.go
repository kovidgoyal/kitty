// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"fmt"
	"syscall"
	"unsafe"
)

var _ = fmt.Print

func Fallocate_simple(fd int, size int64) (err error) {
	store := &syscall.Fstore_t{
		Flags:   syscall.F_ALLOCATEALL,
		Posmode: syscall.F_PEOFPOSMODE,
		Offset:  0,
		Length:  int64(size),
	}

	for {
		if _, _, err = syscall.Syscall(syscall.SYS_FCNTL, uintptr(out.f.Fd()), syscall.F_PREALLOCATE, uintptr(unsafe.Pointer(store))); !errors.Is(err, unix.EINTR) {
			if err != 0 {
				return err
			}
			return nil
		}
	}
}
