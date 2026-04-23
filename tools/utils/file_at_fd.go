package utils

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

// MkdirAt creates a new subdirectory named 'name' inside the directory
// pointed to by parentDir.
func MkdirAt(parentDir *os.File, name string, perm os.FileMode) error {
	// parentDir.Fd() gives us the base directory handle
	fd := int(parentDir.Fd())

	// unix.Mkdirat(dirfd, path, mode)
	// We convert the os.FileMode to a uint32 for the syscall
	err := unix.Mkdirat(fd, name, uint32(perm))
	if err != nil {
		return &os.PathError{
			Op:   "mkdirat",
			Path: name,
			Err:  err,
		}
	}
	return nil
}

// OpenAt opens a file relative to the directory pointed to by dirFile.
// Matches the behavior of os.Open (read-only).
func OpenAt(dirFile *os.File, name string) (*os.File, error) {
	return openAt(dirFile, name, os.O_RDONLY, 0)
}

// Create a symlink named name in the directory pointed to by dirFile. The
// target of the symlink is set to target
func SymlinkAt(dirFile *os.File, name, target string) error {
	return unix.Symlinkat(target, int(dirFile.Fd()), name)
}

// CreateAt creates or truncates a file relative to the directory pointed to by dirFile.
// Matches the behavior of os.Create (read-write, creates if doesn't exist, truncates).
func CreateAt(dirFile *os.File, name string) (*os.File, error) {
	return openAt(dirFile, name, os.O_RDWR|os.O_CREATE|os.O_TRUNC, 0666)
}

// Internal helper to wrap the unix.Openat syscall
func openAt(dirFile *os.File, name string, flags int, perm os.FileMode) (*os.File, error) {
	dirFd := int(dirFile.Fd())

	// Call the underlying system call
	fd, err := unix.Openat(dirFd, name, flags|unix.O_CLOEXEC, uint32(perm))
	if err != nil {
		return nil, &os.PathError{Op: "openat", Path: name, Err: err}
	}
	name = filepath.Join(dirFile.Name(), name)
	// os.NewFile takes the raw fd and the name and returns a high-level *os.File.
	// This allows you to use standard methods like .Read(), .Write(), and .Close().
	return os.NewFile(uintptr(fd), name), nil
}

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
