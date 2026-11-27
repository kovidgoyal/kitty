// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"syscall"
	"unicode/utf8"
)

var _ = fmt.Print

// Return a name for a temporary file in the same directory as path. The name
// is kept short so that it fits within the filesystem's file name length limit
// even when the basename of path is at that limit, while still containing a
// prefix of the basename so that stray temporary files can be identified.
func atomic_temp_name(path string) string {
	dir, base := filepath.Split(path)
	const max_prefix_len = 32
	if len(base) > max_prefix_len {
		n := max_prefix_len
		for n > 0 && !utf8.RuneStart(base[n]) {
			n--
		}
		base = base[:n]
	}
	return dir + "." + base + ".kitty-tmp-" + RandomFilename()
}

// Create a link at newname using create() and atomically rename it into place,
// so that if anything fails any existing file at newname is left untouched.
func atomic_create_link(newname string, create func(tempname string) error) (err error) {
	for {
		tempname := atomic_temp_name(newname)
		if err = create(tempname); err == nil {
			if err = os.Rename(tempname, newname); err != nil {
				os.Remove(tempname)
				if st, serr := os.Lstat(newname); serr == nil && st.IsDir() {
					err = &fs.PathError{Op: "replace", Path: newname, Err: syscall.EISDIR}
				}
			}
			return err
		}
		if !errors.Is(err, fs.ErrExist) {
			return err
		}
	}
}

func AtomicCreateSymlink(oldname, newname string) (err error) {
	err = os.Symlink(oldname, newname)
	if err == nil {
		return nil
	}
	if !errors.Is(err, fs.ErrExist) {
		return err
	}
	if et, err := os.Readlink(newname); err == nil && et == oldname {
		return nil
	}
	return atomic_create_link(newname, func(tempname string) error { return os.Symlink(oldname, tempname) })
}

// Create a hard link at newname pointing to oldname, atomically replacing any
// existing file at newname.
func AtomicCreateHardlink(oldname, newname string) (err error) {
	err = os.Link(oldname, newname)
	if err == nil {
		return nil
	}
	if !errors.Is(err, fs.ErrExist) {
		return err
	}
	// rename() is a no-op when both names refer to the same file, which would
	// leave the temporary link behind, so check for that first.
	if src, serr := os.Lstat(oldname); serr == nil {
		if dest, derr := os.Lstat(newname); derr == nil && os.SameFile(src, dest) {
			return nil
		}
	}
	return atomic_create_link(newname, func(tempname string) error { return os.Link(oldname, tempname) })
}

func AtomicWriteFile(path string, data io.Reader, perm os.FileMode) (err error) {
	npath, err := EvalSymlinksThatExist(path)
	if err == nil {
		path = npath
		path, err = filepath.Abs(path)
		if err == nil {
			var f *os.File
			f, err = os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".atomic-write-")
			if err == nil {
				removed := false
				defer func() {
					if err == nil {
						err = f.Close()
					} else {
						f.Close()
					}
					if !removed {
						os.Remove(f.Name())
						removed = true
					}
				}()
				if _, err = io.Copy(f, data); err == nil {
					if err = f.Chmod(perm); err == nil {
						if err = f.Sync(); err == nil { // Sync before rename to ensure we dont end up with a zero sized file
							if err = os.Rename(f.Name(), path); err == nil {
								removed = true
							}
						}
					}
				}
			}
		}
	}
	return
}

func AtomicUpdateFile(path string, data io.Reader, perms ...fs.FileMode) (err error) {
	perm := fs.FileMode(0o644)
	if len(perms) > 0 {
		perm = perms[0]
	}
	s, err := os.Stat(path)
	if err == nil {
		perm = s.Mode().Perm()
	}
	return AtomicWriteFile(path, data, perm)
}
