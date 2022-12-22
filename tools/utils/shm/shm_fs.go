// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>
//go:build linux || netbsd || openbsd || dragonfly

package shm

import (
	"crypto/sha256"
	"errors"
	"fmt"
	"io/fs"
	"kitty/tools/utils"
	"os"
	"path/filepath"
	"runtime"
)

var _ = fmt.Print

type file_based_mmap struct {
	f            *os.File
	region       []byte
	unlinked     bool
	special_name string
}

func file_mmap(f *os.File, size uint64, access AccessFlags, truncate bool, special_name string) (MMap, error) {
	if truncate {
		err := truncate_or_unlink(f, size)
		if err != nil {
			return nil, err
		}
	}
	region, err := mmap(int(size), access, int(f.Fd()), 0)
	if err != nil {
		f.Close()
		os.Remove(f.Name())
		return nil, err
	}
	return &file_based_mmap{f: f, region: region, special_name: special_name}, nil
}

func (self *file_based_mmap) Name() string {
	if self.special_name != "" {
		return self.special_name
	}
	return filepath.Base(self.f.Name())
}

func (self *file_based_mmap) FileSystemName() string {
	return self.f.Name()
}

func (self *file_based_mmap) Slice() []byte {
	return self.region
}

func (self *file_based_mmap) Close() (err error) {
	if self.region != nil {
		self.f.Close()
		err = munmap(self.region)
		self.region = nil
	}
	return err
}

func (self *file_based_mmap) Unlink() (err error) {
	if self.unlinked {
		return nil
	}
	self.unlinked = true
	return os.Remove(self.f.Name())
}

func (self *file_based_mmap) IsFileSystemBacked() bool { return true }

func file_path_from_name(name string) string {
	// See https://github.com/openbsd/src/blob/master/lib/libc/gen/shm_open.c
	if runtime.GOOS == "openbsd" {
		hash := sha256.Sum256(utils.UnsafeStringToBytes(name))
		return filepath.Join(SHM_DIR, utils.UnsafeBytesToString(hash[:])+".shm")
	}
	return filepath.Join(SHM_DIR, name)
}

func create_temp(pattern string, size uint64) (ans MMap, err error) {
	special_name := ""
	var prefix, suffix string
	prefix, suffix, err = prefix_and_suffix(pattern)
	if err != nil {
		return
	}
	var f *os.File
	try := 0
	for {
		name := prefix + next_random() + suffix
		path := file_path_from_name(name)
		f, err = os.OpenFile(path, os.O_EXCL|os.O_CREATE|os.O_RDWR, 0600)
		if err != nil {
			if errors.Is(err, fs.ErrExist) {
				try += 1
				if try > 10000 {
					return nil, &os.PathError{Op: "createtemp", Path: prefix + "*" + suffix, Err: fs.ErrExist}
				}
				continue
			}
			return
		}
		break
	}
	return file_mmap(f, size, WRITE, true, special_name)
}

func Open(name string, size uint64) (MMap, error) {
	ans, err := os.OpenFile(file_path_from_name(name), os.O_RDONLY, 0)
	if err != nil {
		return nil, err
	}
	return file_mmap(ans, size, READ, false, name)
}
