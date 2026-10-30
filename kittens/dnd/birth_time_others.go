//go:build !linux && !darwin && !freebsd && !netbsd

package dnd

import (
	"os"
	"time"
)

// Return the birth time of the file at path, which must be the file
// described by info, or the zero time if it is unknown.
func birth_time(path string, info os.FileInfo) time.Time {
	return time.Time{}
}
