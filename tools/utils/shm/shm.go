// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"strings"

	"kitty/tools/cli"

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

type MMap interface {
	Close() error
	Unlink() error
	Slice() []byte
	Name() string
	IsFileSystemBacked() bool
	FileSystemName() string
	Stat() (fs.FileInfo, error)
	Flush() error
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

func read_till_buf_full(f *os.File, buf []byte) ([]byte, error) {
	p := buf
	for len(p) > 0 {
		n, err := f.Read(p)
		p = p[n:]
		if err != nil {
			if len(p) == 0 && errors.Is(err, io.EOF) {
				err = nil
			}
			err = fmt.Errorf("Failed to read from SHM file with error: %w", err)
			return buf[:len(buf)-len(p)], err
		}
	}
	return buf, nil
}

func read_with_size(f *os.File) ([]byte, error) {
	szbuf := []byte{0, 0, 0, 0}
	szbuf, err := read_till_buf_full(f, szbuf)
	if err != nil {
		return nil, err
	}
	size := int(binary.BigEndian.Uint32(szbuf))
	return read_till_buf_full(f, make([]byte, size))
}

func WriteWithSize(self MMap, b []byte, at int) error {
	szbuf := []byte{0, 0, 0, 0}
	binary.BigEndian.PutUint32(szbuf, uint32(len(b)))
	copy(self.Slice()[at:], szbuf)
	copy(self.Slice()[at+4:], b)
	return nil
}

func ReadWithSize(self MMap, at int) []byte {
	size := int(binary.BigEndian.Uint32(self.Slice()[at : at+4]))
	return self.Slice()[at+4 : at+4+size]
}

func test_integration_with_python(args []string) (rc int, err error) {
	switch args[0] {
	default:
		return 1, fmt.Errorf("Unknown test type: %s", args[0])
	case "read":
		data, err := ReadWithSizeAndUnlink(args[1])
		if err != nil {
			return 1, err
		}
		_, err = os.Stdout.Write(data)
		if err != nil {
			return 1, err
		}
	case "write":
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			return 1, err
		}
		mmap, err := CreateTemp("shmtest-", uint64(len(data)+4))
		if err != nil {
			return 1, err
		}
		WriteWithSize(mmap, data, 0)
		mmap.Close()
		fmt.Println(mmap.Name())
	}
	return 0, nil
}

func TestEntryPoint(root *cli.Command) {
	root.AddSubCommand(&cli.Command{
		Name:            "shm",
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			return test_integration_with_python(args)
		},
	})

}
