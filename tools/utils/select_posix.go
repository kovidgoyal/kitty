//go:build !darwin

package utils

import (
	"time"

	"golang.org/x/sys/unix"
)

func Select(nfd int, r *unix.FdSet, w *unix.FdSet, e *unix.FdSet, timeout time.Duration) (n int, err error) {
	if timeout < 0 {
		return unix.Pselect(nfd, r, w, e, nil, nil)
	}
	ts := NsecToTimespec(timeout)
	return unix.Pselect(nfd, r, w, e, &ts, nil)
}
