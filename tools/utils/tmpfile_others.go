//go:build !linux

// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"os"
)

var _ = fmt.Print

func CreateAnonymousTemp(dir string) (*os.File, error) {
	f, err := os.CreateTemp(dir, "")
	if err != nil {
		return nil, err
	}
	err = os.Remove(f.Name())
	if err != nil {
		f.Close()
		return nil, err
	}
	return f, err
}
