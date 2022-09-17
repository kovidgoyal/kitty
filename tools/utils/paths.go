// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"io/fs"
	"os"
	"os/user"
	"path/filepath"
	"runtime"
	"strings"

	"golang.org/x/sys/unix"
)

var Sep = string(os.PathSeparator)

func Expanduser(path string) string {
	if !strings.HasPrefix(path, "~") {
		return path
	}
	home, err := os.UserHomeDir()
	if err != nil {
		usr, err := user.Current()
		if err == nil {
			home = usr.HomeDir
		}
	}
	if err != nil || home == "" {
		return path
	}
	if path == "~" {
		return home
	}
	path = strings.ReplaceAll(path, Sep, "/")
	parts := strings.Split(path, "/")
	if parts[0] == "~" {
		parts[0] = home
	} else {
		uname := parts[0][1:]
		if uname != "" {
			u, err := user.Lookup(uname)
			if err == nil && u.HomeDir != "" {
				parts[0] = u.HomeDir
			}
		}
	}
	return strings.Join(parts, Sep)
}

func Abspath(path string) string {
	q, err := filepath.Abs(path)
	if err == nil {
		return q
	}
	return path
}

var config_dir string

func KittyExe() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	ans := filepath.Join(filepath.Dir(exe), "kitty")
	return ans, unix.Access(ans, unix.X_OK)
}

func ConfigDir() string {
	if config_dir != "" {
		return config_dir
	}
	if os.Getenv("KITTY_CONFIG_DIRECTORY") != "" {
		config_dir = Abspath(Expanduser(os.Getenv("KITTY_CONFIG_DIRECTORY")))
	} else {
		var locations []string
		if os.Getenv("XDG_CONFIG_HOME") != "" {
			locations = append(locations, os.Getenv("XDG_CACHE_HOME"))
		}
		locations = append(locations, Expanduser("~/.config"))
		if runtime.GOOS == "darwin" {
			locations = append(locations, Expanduser("~/Library/Preferences"))
		}
		for _, loc := range locations {
			if loc != "" {
				q := filepath.Join(loc, "kitty")
				if _, err := os.Stat(filepath.Join(q, "kitty.conf")); err == nil {
					config_dir = q
					break
				}
			}
		}
		for _, loc := range locations {
			if loc != "" {
				config_dir = filepath.Join(loc, "kitty")
				break
			}
		}
	}

	return config_dir
}

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
		if !strings.HasSuffix(dirpath, Sep) && dirpath != "" {
			path_based_on_original_dir += Sep
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
