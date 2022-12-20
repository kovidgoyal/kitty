// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"errors"
	"fmt"
	"math/rand"
	"os"
	"strconv"
	"strings"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print
var ErrPatternHasSeparator = errors.New("The specified pattern has file path separators in it")
var ErrPatternTooLong = errors.New("The specified pattern for the SHM name is too long")

type ErrNotSupported struct {
	err error
}

func (self *ErrNotSupported) Error() string {
	return fmt.Sprintf("POSIX shared memory not supported on this platform: with underlying error: %v", self.err)
}

// prefix_and_suffix splits pattern by the last wildcard "*", if applicable,
// returning prefix as the part before "*" and suffix as the part after "*".
func prefix_and_suffix(pattern string) (prefix, suffix string, err error) {
	for i := 0; i < len(pattern); i++ {
		if os.IsPathSeparator(pattern[i]) {
			return "", "", ErrPatternHasSeparator
		}
	}
	if pos := strings.LastIndexByte(pattern, '*'); pos != -1 {
		prefix, suffix = pattern[:pos], pattern[pos+1:]
	} else {
		prefix = pattern
	}
	return prefix, suffix, nil
}

func next_random() string {
	num := rand.Uint32()
	return strconv.FormatUint(uint64(num), 16)
}

type MMap interface {
	Close() error
	Unlink() error
	Slice() []byte
	Name() string
	IsFilesystemBacked() bool
}

type AccessFlags int

const (
	READ AccessFlags = iota
	WRITE
	COPY
)

func mmap(sz int, access AccessFlags, fd int, off int64) ([]byte, error) {
	flags := unix.MAP_SHARED
	prot := unix.PROT_READ
	switch access {
	case COPY:
		prot |= unix.PROT_WRITE
		flags = unix.MAP_PRIVATE
	case WRITE:
		prot |= unix.PROT_WRITE
	}

	b, err := unix.Mmap(fd, off, sz, prot, flags)
	if err != nil {
		return nil, err
	}
	return b, nil
}

func munmap(s []byte) error {
	return unix.Munmap(s)
}

type file_based_mmap struct {
	f        *os.File
	region   []byte
	unlinked bool
}

func file_mmap(f *os.File, size uint64, access AccessFlags, truncate bool) (MMap, error) {
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
	return &file_based_mmap{f: f, region: region}, nil
}

func (self *file_based_mmap) Name() string {
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

func (self *file_based_mmap) IsFilesystemBacked() bool { return true }

func CreateTemp(pattern string, size uint64) (MMap, error) {
	return create_temp(pattern, size)
}

func truncate_or_unlink(ans *os.File, size uint64) (err error) {
	for {
		err = unix.Ftruncate(int(ans.Fd()), int64(size))
		if !errors.Is(err, unix.EINTR) {
			break
		}
	}
	if err != nil {
		ans.Close()
		os.Remove(ans.Name())
		return fmt.Errorf("Failed to ftruncate() SHM file %s to size: %d with error: %w", ans.Name(), size, err)
	}
	return
}
