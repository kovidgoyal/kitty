//go:build linux || darwin

package utils

import (
	"time"

	"golang.org/x/sys/unix"
)

func MonotonicRaw() (time.Time, error) {
	ts := unix.Timespec{}
	if err := unix.ClockGettime(unix.CLOCK_MONOTONIC_RAW, &ts); err != nil {
		return time.Time{}, err
	}
	s, ns := ts.Unix()
	return time.Unix(s, ns), nil
}
