// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"mime"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/utils"
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
	Name, CompletionCandidate, Abspath string
	Mode                               os.FileMode
	IsDir, IsSymlink, IsEmptyDir       bool
}

func CompleteFiles(prefix string, callback func(*FileEntry), cwd string) error {
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
			Name: entry.Name(), Abspath: abspath, Mode: entry.Type(), IsDir: entry.IsDir(),
			IsSymlink: entry.Type()&os.ModeSymlink == os.ModeSymlink, CompletionCandidate: q}
		if data.IsSymlink {
			target, err := filepath.EvalSymlinks(abspath)
			if err == nil && target != base_dir {
				td, err := os.Stat(target)
				if err == nil && td.IsDir() {
					dir_to_check = target
					data.IsDir = true
				}
			}
		}
		if dir_to_check != "" {
			subentries, err := os.ReadDir(dir_to_check)
			data.IsEmptyDir = err != nil || len(subentries) == 0
		}
		if data.IsDir {
			data.CompletionCandidate += utils.Sep
		}
		callback(&data)
	}
	return nil
}

func CompleteExecutablesInPath(prefix string, paths ...string) []string {
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
	_ = CompleteFiles(prefix, func(entry *FileEntry) {
		if entry.IsDir && !entry.IsEmptyDir {
			entries, err := os.ReadDir(entry.Abspath)
			if err == nil {
				for _, e := range entries {
					if is_match(e.Name()) || is_dir_or_symlink_to_dir(e, filepath.Join(entry.Abspath, e.Name())) {
						ans = append(ans, entry.CompletionCandidate)
						return
					}
				}
			}
			return
		}
		q := strings.ToLower(entry.Name)
		if is_match(q) {
			ans = append(ans, entry.CompletionCandidate)
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
	all_allowed := false
	for _, p := range patterns {
		if p == "*" {
			all_allowed = true
			break
		}
	}
	return fname_based_completer(prefix, cwd, func(name string) bool {
		if all_allowed {
			return true
		}
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

func make_completer(title string, relative_to relative_to, patterns []string, f func(string, string, []string) []string) CompletionFunc {
	lpats := make([]string, 0, len(patterns))
	for _, p := range patterns {
		lpats = append(lpats, strings.ToLower(p))
	}
	cwd := get_cwd_for_completion(relative_to)

	return func(completions *Completions, word string, arg_num int) {
		q := f(word, cwd, lpats)
		if len(q) > 0 {
			dirs, files := make([]string, 0, len(q)), make([]string, 0, len(q))
			for _, x := range q {
				if strings.HasSuffix(x, "/") {
					dirs = append(dirs, x)
				} else {
					files = append(files, x)
				}
			}
			if len(dirs) > 0 {
				mg := completions.AddMatchGroup("Directories")
				mg.IsFiles = true
				mg.NoTrailingSpace = true
				for _, c := range dirs {
					mg.AddMatch(c)
				}
			}
			mg := completions.AddMatchGroup(title)
			mg.IsFiles = true
			for _, c := range files {
				mg.AddMatch(c)
			}
		}
	}
}

func CompleteExecutableFirstArg(completions *Completions, word string, arg_num int) {
	if arg_num > 1 {
		completions.Delegate.NumToRemove = completions.CurrentCmd.IndexOfFirstArg + 1 // +1 because the first word is not present in all_words
		completions.Delegate.Command = completions.AllWords[completions.CurrentCmd.IndexOfFirstArg]
		return
	}
	exes := CompleteExecutablesInPath(word)
	if len(exes) > 0 {
		mg := completions.AddMatchGroup("Executables in PATH")
		for _, exe := range exes {
			mg.AddMatch(exe)
		}
	}

	if len(word) > 0 {
		mg := completions.AddMatchGroup("Executables")
		mg.IsFiles = true

		_ = CompleteFiles(word, func(entry *FileEntry) {
			if entry.IsDir && !entry.IsEmptyDir {
				// only allow directories that have sub-dirs or executable files in them
				entries, err := os.ReadDir(entry.Abspath)
				if err == nil {
					for _, x := range entries {
						if x.IsDir() || unix.Access(filepath.Join(entry.Abspath, x.Name()), unix.X_OK) == nil {
							mg.AddMatch(entry.CompletionCandidate)
							break
						}
					}
				}
			} else if unix.Access(entry.Abspath, unix.X_OK) == nil {
				mg.AddMatch(entry.CompletionCandidate)
			}
		}, "")
	}
}

func FnmatchCompleter(title string, relative_to relative_to, patterns ...string) CompletionFunc {
	return make_completer(title, relative_to, patterns, complete_by_fnmatch)
}

func MimepatCompleter(title string, relative_to relative_to, patterns ...string) CompletionFunc {
	return make_completer(title, relative_to, patterns, complete_by_mimepat)
}

func DirectoryCompleter(title string, relative_to relative_to) CompletionFunc {
	if title == "" {
		title = "Directories"
	}
	cwd := get_cwd_for_completion(relative_to)

	return func(completions *Completions, word string, arg_num int) {
		mg := completions.AddMatchGroup(title)
		mg.NoTrailingSpace = true
		mg.IsFiles = true
		_ = CompleteFiles(word, func(entry *FileEntry) {
			if entry.Mode.IsDir() {
				mg.AddMatch(entry.CompletionCandidate)
			}
		}, cwd)
	}
}
