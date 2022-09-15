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
	base := prefix
	if base != "~" && base != "./" && base != "/" {
		// cant use filepath.Dir() as it calls filepath.Clean() which
		// can cause base to no longer match prefix
		idx := strings.LastIndex(base, string(os.PathSeparator))
		if idx > 0 {
			base = base[:idx]
		} else {
			base = ""
		}
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
		if strings.HasPrefix(completion_candidate, prefix) {
			return callback(completion_candidate, abspath, d)
		}
		if d.IsDir() {
			return fs.SkipDir
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

func complete_by_fnmatch(prefix string, patterns []string) []string {
	ans := make([]string, 0, 1024)
	complete_files(prefix, func(completion_candidate, abspath string, d fs.DirEntry) error {
		q := strings.ToLower(filepath.Base(abspath))
		for _, pat := range patterns {
			matched, err := filepath.Match(pat, q)
			if err == nil && matched {
				ans = append(ans, completion_candidate)
			}
		}
		return nil
	})
	return ans
}

func fnmatch_completer(title string, patterns ...string) completion_func {
	lpats := make([]string, 0, len(patterns))
	for _, p := range patterns {
		lpats = append(lpats, strings.ToLower(p))
	}

	return func(completions *Completions, word string, arg_num int) {
		q := complete_by_fnmatch(word, lpats)
		if len(q) > 0 {
			mg := completions.add_match_group(title)
			mg.IsFiles = true
			for _, c := range q {
				mg.add_match(c)
			}
		}
	}
}
