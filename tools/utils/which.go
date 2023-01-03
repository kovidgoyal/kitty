// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func Which(cmd string) string {
	if strings.Contains(cmd, string(os.PathSeparator)) {
		return ""
	}
	path := os.Getenv("PATH")
	if path == "" {
		return ""
	}
	for _, dir := range strings.Split(path, string(os.PathListSeparator)) {
		q := filepath.Join(dir, cmd)
		if unix.Access(q, unix.X_OK) == nil {
			s, err := os.Stat(q)
			if err == nil && !s.IsDir() {
				return q
			}
		}

	}
	return ""
}
