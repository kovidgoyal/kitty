// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

var _ = fmt.Print

type CompleteFilesCallback func(completion_candidate string, abspath string, d fs.DirEntry) error

func complete_files(prefix string, callback CompleteFilesCallback) error {
	base := "."
	base_len := len(base) + 1
	has_cwd_prefix := strings.HasPrefix(prefix, "./")
	is_abs_path := filepath.IsAbs(prefix)
	wd := ""
	if is_abs_path {
		base = prefix
		base_len = 0
		if s, err := os.Stat(prefix); err != nil || !s.IsDir() {
			base = filepath.Dir(prefix)
		}
	} else {
		wd, _ = os.Getwd()
	}
	filepath.WalkDir(base, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if path == base {
			return nil
		}
		completion_candidate := path
		abspath := path
		if is_abs_path {
			completion_candidate = path[base_len:]
		} else {
			abspath = filepath.Join(wd, path)
			if has_cwd_prefix {
				completion_candidate = "./" + completion_candidate
			}
		}
		if strings.HasPrefix(completion_candidate, prefix) {
			return callback(completion_candidate, abspath, d)
		}
		return nil
	})

	return nil
}
