// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>
//go:build darwin || freebsd

package shm

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"strings"
	"unsafe"

	"github.com/kovidgoyal/kitty/tools/utils"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

// ByteSliceFromString makes a zero terminated byte slice from the string
func ByteSliceFromString(s string) []byte {
	a := make([]byte, len(s)+1)
	copy(a, s)
	return a
}

func BytePtrFromString(s string) *byte {
	a := ByteSliceFromString(s)
	return &a[0]
}

func shm_unlink(name string) (err error) {
	bname := BytePtrFromString(name)
	for {
		_, _, errno := unix.Syscall(unix.SYS_SHM_UNLINK, uintptr(unsafe.Pointer(bname)), 0, 0)
		if errno != unix.EINTR {
			if errno != 0 {
				if errno == unix.ENOENT {
					err = fs.ErrNotExist
				} else {
					err = fmt.Errorf("shm_unlink() failed with error: %w", errno)
				}
			}
			break
		}
	}
	return
}

func ShmUnlink(name string) error {
	return shm_unlink(name)
}

func shm_open(name string, flags, perm int) (ans *os.File, err error) {
	bname := BytePtrFromString(name)
	var fd uintptr
	var errno unix.Errno
	for {
		fd, _, errno = unix.Syscall(unix.SYS_SHM_OPEN, uintptr(unsafe.Pointer(bname)), uintptr(flags), uintptr(perm))
		if errno != unix.EINTR {
			if errno != 0 {
				err = fmt.Errorf("shm_open() failed with error: %w", errno)
			}
			break
		}
	}
	if err == nil {
		ans = os.NewFile(fd, name)
	}
	return
}

type syscall_based_mmap struct {
	f        *os.File
	pos      int64
	region   []byte
	unlinked bool
}

func syscall_mmap(f *os.File, size uint64, access AccessFlags, truncate bool) (MMap, error) {
	if truncate {
		err := truncate_or_unlink(f, size, shm_unlink)
		if err != nil {
			return nil, fmt.Errorf("truncate failed with error: %w", err)
		}
	}
	region, err := mmap(int(size), access, int(f.Fd()), 0)
	if err != nil {
		_ = f.Close()
		_ = shm_unlink(f.Name())
		return nil, fmt.Errorf("mmap failed with error: %w", err)
	}
	return &syscall_based_mmap{f: f, region: region}, nil
}

func (self *syscall_based_mmap) Name() string {
	return self.f.Name()
}
func (self *syscall_based_mmap) Stat() (fs.FileInfo, error) {
	return self.f.Stat()
}

func (self *syscall_based_mmap) Flush() error {
	return unix.Msync(self.region, unix.MS_SYNC)
}

func (self *syscall_based_mmap) Slice() []byte {
	return self.region
}

func (self *syscall_based_mmap) Close() (err error) {
	if self.region != nil {
		self.f.Close()
		munmap(self.region)
		self.region = nil
	}
	return
}

func (self *syscall_based_mmap) Unlink() (err error) {
	if self.unlinked {
		return nil
	}
	self.unlinked = true
	return shm_unlink(self.Name())
}

func (self *syscall_based_mmap) Seek(offset int64, whence int) (ret int64, err error) {
	switch whence {
	case io.SeekStart:
		self.pos = offset
	case io.SeekEnd:
		self.pos = int64(len(self.region)) + offset
	case io.SeekCurrent:
		self.pos += offset
	}
	return self.pos, nil
}

func (self *syscall_based_mmap) Read(b []byte) (n int, err error) {
	return Read(self, b)
}

func (self *syscall_based_mmap) Write(b []byte) (n int, err error) {
	return Write(self, b)
}

func (self *syscall_based_mmap) IsFileSystemBacked() bool { return false }
func (self *syscall_based_mmap) FileSystemName() string   { return "" }

func create_temp(pattern string, size uint64) (ans MMap, err error) {
	var prefix, suffix string
	prefix, suffix, err = prefix_and_suffix(pattern)
	if err != nil {
		return
	}
	if SHM_REQUIRED_PREFIX != "" && !strings.HasPrefix(pattern, SHM_REQUIRED_PREFIX) {
		// FreeBSD requires name to start with /
		prefix = SHM_REQUIRED_PREFIX + prefix
	}
	var f *os.File
	try := 0
	for {
		name := prefix + utils.RandomFilename() + suffix
		if len(name) > SHM_NAME_MAX {
			return nil, ErrPatternTooLong
		}
		f, err = shm_open(name, os.O_EXCL|os.O_CREATE|os.O_RDWR, 0600)
		if err != nil && (errors.Is(err, fs.ErrExist) || errors.Unwrap(err) == unix.EEXIST) {
			try += 1
			if try > 10000 {
				return nil, &os.PathError{Op: "createtemp", Path: prefix + "*" + suffix, Err: fs.ErrExist}
			}
			continue
		}
		break
	}
	if err != nil {
		return nil, err
	}
	return syscall_mmap(f, size, WRITE, true)
}

func Open(name string, size uint64) (MMap, error) {
	ans, err := shm_open(name, os.O_RDONLY, 0)
	if err != nil {
		return nil, err
	}
	if size == 0 {
		s, err := ans.Stat()
		if err != nil {
			ans.Close()
			return nil, fmt.Errorf("Failed to stat SHM file with error: %w", err)
		}
		size = uint64(s.Size())
	}
	return syscall_mmap(ans, size, READ, false)
}
