//go:build darwin || freebsd || netbsd

package dnd

import (
	"os"
	"syscall"
	"time"
)

// Return the birth time of the file at path, which must be the file
// described by info, or the zero time if it is unknown.
func birth_time(path string, info os.FileInfo) time.Time {
	if st, ok := info.Sys().(*syscall.Stat_t); ok {
		return time.Unix(st.Birthtimespec.Unix())
	}
	return time.Time{}
}
