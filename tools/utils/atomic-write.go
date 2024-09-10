// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
)

var _ = fmt.Print

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
	for {
		tempname := newname + RandomFilename()
		err = os.Symlink(oldname, tempname)
		if err == nil {
			err = os.Rename(tempname, newname)
			if err != nil {
				os.Remove(tempname)
			}
			return err
		}
		if !errors.Is(err, fs.ErrExist) {
			return err
		}
	}
}

func AtomicWriteFile(path string, data io.Reader, perm os.FileMode) (err error) {
	npath, err := filepath.EvalSymlinks(path)
	if errors.Is(err, fs.ErrNotExist) {
		err = nil
		npath = path
	}
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
