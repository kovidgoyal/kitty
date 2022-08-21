//go:build darwin

package utils

import (
	"os"
	"time"

	"golang.org/x/sys/unix"
)

// Go unix does not wrap pselect on darwin

func Select(nfd int, r *unix.FdSet, w *unix.FdSet, e *unix.FdSet, timeout time.Duration) (n int, err error) {
	deadline := time.Now().Add(timeout)
	for {
		t := deadline.Sub(time.Now())
		if t < 0 {
			t = 0
		}
		ts := NsecToTimeval(t)
		q, qerr := unix.Select(nfd, r, w, w, &ts)
		if qerr == unix.EINTR {
			if time.Now().After(deadline) {
				return 0, os.ErrDeadlineExceeded
			}
			continue
		}
		return q, qerr
	}
}
