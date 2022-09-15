// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"fmt"
	"io/fs"
	"kitty/tools/utils"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

type CompleteFilesCallback func(completion_candidate, abspath string, d fs.DirEntry) error
type Walk_callback func(path, abspath string, d fs.DirEntry, err error) error

func transform_symlink(path string) string {
	if q, err := filepath.EvalSymlinks(path); err == nil {
		return q
	}
	return path
}

func needs_symlink_recurse(path string, d fs.DirEntry) bool {
	if d.Type()&os.ModeSymlink == os.ModeSymlink {
		if s, serr := os.Stat(path); serr == nil && s.IsDir() {
			return true
		}
	}
	return false
}

type transformed_walker struct {
	seen               map[string]bool
	real_callback      Walk_callback
	transform_func     func(string) string
	needs_recurse_func func(string, fs.DirEntry) bool
}

var sep = string(os.PathSeparator)

func (self *transformed_walker) walk(dirpath string) error {
	resolved_path := self.transform_func(dirpath)
	if self.seen[resolved_path] {
		return nil
	}
	self.seen[resolved_path] = true

	c := func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			// Happens if ReadDir on d failed, skip it in that case
			return fs.SkipDir
		}
		rpath, err := filepath.Rel(resolved_path, path)
		if err != nil {
			return err
		}
		// we cant use filepath.Join here as it calls Clean() which can alter dirpath if it contains .. or . etc.
		path_based_on_original_dir := dirpath
		if !strings.HasSuffix(dirpath, sep) {
			path_based_on_original_dir += sep
		}
		path_based_on_original_dir += rpath
		if self.needs_recurse_func(path, d) {
			err = self.walk(path_based_on_original_dir)
		} else {
			err = self.real_callback(path_based_on_original_dir, path, d, err)
		}
		return err
	}

	return filepath.WalkDir(resolved_path, c)
}

// Walk, recursing into symlinks that point to directories. Ignores directories
// that could not be read.
func WalkWithSymlink(dirpath string, callback Walk_callback, transformers ...func(string) string) error {

	transform := func(path string) string {
		for _, t := range transformers {
			path = t(path)
		}
		return transform_symlink(path)
	}
	sw := transformed_walker{
		seen: make(map[string]bool), real_callback: callback, transform_func: transform, needs_recurse_func: needs_symlink_recurse}
	return sw.walk(dirpath)
}

func absolutize_path(path string) string {
	path = utils.Expanduser(path)
	q, err := filepath.Abs(path)
	if err == nil {
		path = q
	}
	return path
}

func complete_files(prefix string, callback CompleteFilesCallback) error {
	abspath := absolutize_path(prefix)
	base := prefix
	if s, err := os.Stat(abspath); err != nil || !s.IsDir() {
		base = filepath.Dir(prefix)
	}
	num := 0
	WalkWithSymlink(base, func(path, abspath string, d fs.DirEntry, err error) error {
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
