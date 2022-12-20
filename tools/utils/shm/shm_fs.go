// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>
//go:build linux || netbsd

package shm

import (
	"fmt"
	"os"
	"path/filepath"
)

var _ = fmt.Print

func create_temp(pattern string, size uint64) (MMap, error) {
	ans, err := os.CreateTemp(SHM_DIR, pattern)
	if err != nil {
		return nil, err
	}
	return file_mmap(ans, size, WRITE, true)
}

func Open(name string, size uint64) (MMap, error) {
	if !filepath.IsAbs(name) {
		name = filepath.Join(SHM_DIR, name)
	}
	ans, err := os.OpenFile(name, os.O_RDONLY, 0)
	if err != nil {
		return nil, err
	}
	return file_mmap(ans, size, READ, false)
}
