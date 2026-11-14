package dnd

import (
	"os"
	"time"

	"golang.org/x/sys/unix"
)

// Return the birth time of the file at path, which must be the file
// described by info, or the zero time if it is unknown.
func birth_time(path string, info os.FileInfo) time.Time {
	var sx unix.Statx_t
	for {
		err := unix.Statx(unix.AT_FDCWD, path, unix.AT_SYMLINK_NOFOLLOW, unix.STATX_INO|unix.STATX_BTIME, &sx)
		if err == nil {
			break
		}
		if err != unix.EINTR {
			return time.Time{}
		}
	}
	if sx.Mask&unix.STATX_BTIME == 0 {
		return time.Time{}
	}
	// The path may have been replaced since info was obtained
	dev, ino, err := file_identity(info)
	if err != nil || ino != sx.Ino || dev != unix.Mkdev(sx.Dev_major, sx.Dev_minor) {
		return time.Time{}
	}
	return time.Unix(sx.Btime.Sec, int64(sx.Btime.Nsec))
}
