// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"fmt"
	"mime"
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

type FileEntry struct {
	name, completion_candidate, abspath string
	mode                                os.FileMode
	is_dir, is_symlink, is_empty_dir    bool
}

func complete_files(prefix string, callback func(*FileEntry), cwd string) error {
	if cwd == "" {
		var err error
		cwd, err = os.Getwd()
		if err != nil {
			return err
		}
	}
	location := absolutize_path(prefix)
	base_dir := ""
	joinable_prefix := ""
	switch prefix {
	case ".":
		base_dir = "."
		joinable_prefix = ""
	case "./":
		base_dir = "."
		joinable_prefix = "./"
	case "/":
		base_dir = "/"
		joinable_prefix = "/"
	case "~":
		base_dir = location
		joinable_prefix = "~/"
	case "":
		base_dir = cwd
		joinable_prefix = ""
	default:
		if strings.HasSuffix(prefix, utils.Sep) {
			base_dir = location
			joinable_prefix = prefix
		} else {
			idx := strings.LastIndex(prefix, utils.Sep)
			if idx > 0 {
				joinable_prefix = prefix[:idx+1]
				base_dir = filepath.Dir(location)
			}
		}
	}
	if base_dir == "" {
		base_dir = cwd
	}
	if !strings.HasPrefix(base_dir, "~") && !filepath.IsAbs(base_dir) {
		base_dir = filepath.Join(cwd, base_dir)
	}
	// fmt.Printf("prefix=%#v base_dir=%#v joinable_prefix=%#v\n", prefix, base_dir, joinable_prefix)
	entries, err := os.ReadDir(base_dir)
	if err != nil {
		return err
	}

	for _, entry := range entries {
		q := joinable_prefix + entry.Name()
		if !strings.HasPrefix(q, prefix) {
			continue
		}
		abspath := filepath.Join(base_dir, entry.Name())
		dir_to_check := ""
		data := FileEntry{
			name: entry.Name(), abspath: abspath, mode: entry.Type(), is_dir: entry.IsDir(),
			is_symlink: entry.Type()&os.ModeSymlink == os.ModeSymlink, completion_candidate: q}
		if data.is_symlink {
			target, err := filepath.EvalSymlinks(abspath)
			if err == nil && target != base_dir {
				td, err := os.Stat(target)
				if err == nil && td.IsDir() {
					dir_to_check = target
					data.is_dir = true
				}
			}
		}
		if dir_to_check != "" {
			subentries, err := os.ReadDir(dir_to_check)
			data.is_empty_dir = err != nil || len(subentries) == 0
		}
		if data.is_dir {
			data.completion_candidate += utils.Sep
		}
		callback(&data)
	}
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

func is_dir_or_symlink_to_dir(entry os.DirEntry, path string) bool {
	if entry.IsDir() {
		return true
	}
	if entry.Type()&os.ModeSymlink == os.ModeSymlink {
		p, err := filepath.EvalSymlinks(path)
		if err == nil {
			s, err := os.Stat(p)
			if err == nil && s.IsDir() {
				return true
			}
		}
	}
	return false
}

func fname_based_completer(prefix, cwd string, is_match func(string) bool) []string {
	ans := make([]string, 0, 1024)
	complete_files(prefix, func(entry *FileEntry) {
		if entry.is_dir && !entry.is_empty_dir {
			entries, err := os.ReadDir(entry.abspath)
			if err == nil {
				for _, e := range entries {
					if is_match(e.Name()) || is_dir_or_symlink_to_dir(e, filepath.Join(entry.abspath, e.Name())) {
						ans = append(ans, entry.completion_candidate)
						return
					}
				}
			}
			return
		}
		q := strings.ToLower(entry.name)
		if is_match(q) {
			ans = append(ans, entry.completion_candidate)
		}
	}, cwd)
	return ans

}

func complete_by_fnmatch(prefix, cwd string, patterns []string) []string {
	return fname_based_completer(prefix, cwd, func(name string) bool {
		for _, pat := range patterns {
			matched, err := filepath.Match(pat, name)
			if err == nil && matched {
				return true
			}
		}
		return false
	})
}

func complete_by_mimepat(prefix, cwd string, patterns []string) []string {
	return fname_based_completer(prefix, cwd, func(name string) bool {
		idx := strings.Index(name, ".")
		if idx < 1 {
			return false
		}
		ext := name[idx:]
		mt := mime.TypeByExtension(ext)
		if mt == "" {
			ext = filepath.Ext(name)
			mt = mime.TypeByExtension(ext)
		}
		if mt == "" {
			return false
		}
		for _, pat := range patterns {
			matched, err := filepath.Match(pat, mt)
			if err == nil && matched {
				return true
			}
		}
		return false
	})
}

type relative_to int

const (
	CWD relative_to = iota
	CONFIG
)

func get_cwd_for_completion(relative_to relative_to) string {
	switch relative_to {
	case CONFIG:
		return utils.ConfigDir()
	}
	return ""
}

func make_completer(title string, relative_to relative_to, patterns []string, f func(string, string, []string) []string) completion_func {
	lpats := make([]string, 0, len(patterns))
	for _, p := range patterns {
		lpats = append(lpats, strings.ToLower(p))
	}
	cwd := get_cwd_for_completion(relative_to)

	return func(completions *Completions, word string, arg_num int) {
		q := f(word, cwd, lpats)
		if len(q) > 0 {
			mg := completions.add_match_group(title)
			mg.IsFiles = true
			for _, c := range q {
				mg.add_match(c)
			}
		}
	}
}

func fnmatch_completer(title string, relative_to relative_to, patterns ...string) completion_func {
	return make_completer(title, relative_to, patterns, complete_by_fnmatch)
}

func mimepat_completer(title string, relative_to relative_to, patterns ...string) completion_func {
	return make_completer(title, relative_to, patterns, complete_by_mimepat)
}

func directory_completer(title string, relative_to relative_to) completion_func {
	if title == "" {
		title = "Directories"
	}
	cwd := get_cwd_for_completion(relative_to)

	return func(completions *Completions, word string, arg_num int) {
		mg := completions.add_match_group(title)
		mg.IsFiles = true
		complete_files(word, func(entry *FileEntry) {
			if entry.mode.IsDir() {
				mg.add_match(entry.completion_candidate)
			}
		}, cwd)
	}
}
