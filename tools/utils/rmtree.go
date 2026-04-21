package utils

import (
	"errors"
	"fmt"
	"io"
	"os"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

// RemoveChildren recursively removes all files and subdirectories
// within the directory pointed to by dirFile. Removes all it can but returns
// the first error, if any.
func RemoveChildren(dirFile *os.File) error {
	fd := int(dirFile.Fd())
	var firstErr error

	// Rewind directory pointer to ensure we start from the beginning
	if _, err := dirFile.Seek(0, 0); err != nil {
		return &os.PathError{Op: "seek", Path: dirFile.Name(), Err: err}
	}

	for {
		// Read names in small chunks to handle very large directories
		names, err := dirFile.Readdirnames(64)
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			if firstErr == nil {
				firstErr = &os.PathError{Op: "readdirnames", Path: dirFile.Name(), Err: err}
			}
			break
		}

		for _, name := range names {
			var stat unix.Stat_t
			// Get file info relative to the parent FD
			err := unix.Fstatat(fd, name, &stat, unix.AT_SYMLINK_NOFOLLOW)
			if err != nil {
				if firstErr == nil {
					firstErr = &os.PathError{Op: "fstatat", Path: name, Err: err}
				}
				continue
			}

			if (stat.Mode & unix.S_IFMT) == unix.S_IFDIR {
				// Open subdirectory relative to parent FD
				childFd, err := unix.Openat(fd, name, unix.O_RDONLY|unix.O_DIRECTORY|unix.O_CLOEXEC, 0)
				if err != nil {
					if firstErr == nil {
						firstErr = &os.PathError{Op: "openat", Path: name, Err: err}
					}
					continue
				}

				childFile := os.NewFile(uintptr(childFd), name)
				if err := RemoveChildren(childFile); err != nil && firstErr == nil {
					firstErr = err
				}
				childFile.Close()

				// Remove the empty subdirectory
				if err := unix.Unlinkat(fd, name, unix.AT_REMOVEDIR); err != nil && firstErr == nil {
					firstErr = &os.PathError{Op: "unlinkat", Path: name, Err: err}
				}
			} else {
				// Remove file/symlink
				if err := unix.Unlinkat(fd, name, 0); err != nil && firstErr == nil {
					firstErr = &os.PathError{Op: "unlinkat", Path: name, Err: err}
				}
			}
		}
	}
	_, _ = dirFile.Seek(0, 0)
	return firstErr
}
