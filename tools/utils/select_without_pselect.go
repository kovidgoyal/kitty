//go:build darwin

package utils

import (
	"os"
	"time"

	"golang.org/x/sys/unix"
)

// Go unix does not wrap pselect on darwin

func Select(nfd int, r *unix.FdSet, w *unix.FdSet, e *unix.FdSet, timeout time.Duration) (n int, err error) {
	if timeout < 0 {
		return unix.Select(nfd, r, w, e, nil)
	}
	ts := NsecToTimeval(timeout)
	return unix.Select(nfd, r, w, e, &ts)
}
