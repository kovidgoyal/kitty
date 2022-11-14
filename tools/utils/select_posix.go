// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

//go:build linux

package utils

import (
	"time"

	"golang.org/x/sys/unix"
)

func Select(nfd int, r *unix.FdSet, w *unix.FdSet, e *unix.FdSet, timeout time.Duration) (n int, err error) {
	if timeout < 0 {
		return unix.Pselect(nfd, r, w, e, nil, nil)
	}
	ts := unix.NsecToTimespec(int64(timeout))
	return unix.Pselect(nfd, r, w, e, &ts, nil)
}
