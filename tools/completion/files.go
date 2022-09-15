// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"

	"kitty/tools/utils"
)

var _ = fmt.Print

func absolutize_path(path string) string {
	path = utils.Expanduser(path)
	q, err := filepath.Abs(path)
	if err == nil {
		path = q
	}
	return path
}

type CompleteFilesCallback func(completion_candidate, abspath string, d fs.DirEntry) error

func complete_files(prefix string, callback CompleteFilesCallback) error {
	abspath := absolutize_path(prefix)
	base := prefix
	if s, err := os.Stat(abspath); err != nil || !s.IsDir() {
		base = filepath.Dir(prefix)
	}
	num := 0
	utils.WalkWithSymlink(base, func(path, abspath string, d fs.DirEntry, err error) error {
		if err != nil {
			return fs.SkipDir
		}
		num++
		if num == 1 {
			return nil
		}
		completion_candidate := path
		if strings.HasPrefix(completion_candidate, prefix) && completion_candidate != prefix {
			return callback(completion_candidate, abspath, d)
		}
		return nil
	}, absolutize_path)

	return nil
}

func complete_executables_in_path(prefix string, paths ...string) []string {
	ans := make([]string, 0, 1024)
	if len(paths) == 0 {
		paths = filepath.SplitList(os.Getenv("PATH"))
	}
	for _, dir := range paths {
		entries, err := os.ReadDir(dir)
		if err == nil {
			for _, e := range entries {
				if strings.HasPrefix(e.Name(), prefix) && !e.IsDir() && unix.Access(filepath.Join(dir, e.Name()), unix.X_OK) == nil {
					ans = append(ans, e.Name())
				}
			}
		}
	}
	return ans
}
