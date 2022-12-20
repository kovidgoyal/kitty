// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"fmt"
	"os"
	"path/filepath"
)

var _ = fmt.Print

const SHM_DIR = "/tmp"

func create_temp(pattern string) (*os.File, error) {
	ans, err := os.CreateTemp(SHM_DIR, pattern)
	if err != nil {
		return nil, err
	}
	return ans, nil
}

func Open(name string) (*os.File, error) {
	if !filepath.IsAbs(name) {
		name = filepath.Join(SHM_DIR, name)
	}
	ans, err := os.OpenFile(name, os.O_RDONLY, 0)
	if err != nil {
		return nil, err
	}
	return ans, nil
}

func Unlink(name string) error {
	if !filepath.IsAbs(name) {
		name = filepath.Join(SHM_DIR, name)
	}
	return os.Remove(name)

}
