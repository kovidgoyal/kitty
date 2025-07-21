// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"crypto/md5"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print
var path_name_map, remote_dirs map[string]string

var mimetypes_cache, data_cache, hash_cache *utils.LRUCache[string, string]
var size_cache *utils.LRUCache[string, int64]
var lines_cache *utils.LRUCache[string, []string]
var light_highlighted_lines_cache *utils.LRUCache[string, []string]
var dark_highlighted_lines_cache *utils.LRUCache[string, []string]
var is_text_cache *utils.LRUCache[string, bool]

func init_caches() {
	path_name_map = make(map[string]string, 32)
	remote_dirs = make(map[string]string, 32)
	const sz = 4096
	size_cache = utils.NewLRUCache[string, int64](sz)
	mimetypes_cache = utils.NewLRUCache[string, string](sz)
	data_cache = utils.NewLRUCache[string, string](sz)
	is_text_cache = utils.NewLRUCache[string, bool](sz)
	lines_cache = utils.NewLRUCache[string, []string](sz)
	light_highlighted_lines_cache = utils.NewLRUCache[string, []string](sz)
	dark_highlighted_lines_cache = utils.NewLRUCache[string, []string](sz)
	hash_cache = utils.NewLRUCache[string, string](sz)
}

func add_remote_dir(val string) {
	x := filepath.Base(val)
	idx := strings.LastIndex(x, "-")
	if idx > -1 {
		x = x[idx+1:]
	} else {
		x = ""
	}
	remote_dirs[val] = x
}

func mimetype_for_path(path string) string {
	return mimetypes_cache.MustGetOrCreate(path, func(path string) string {
		mt := utils.GuessMimeTypeWithFileSystemAccess(path)
		if mt == "" {
			mt = "application/octet-stream"
		}
		if utils.KnownTextualMimes[mt] {
			if _, a, found := strings.Cut(mt, "/"); found {
				mt = "text/" + a
			}
		}
		return mt
	})
}

func data_for_path(path string) (string, error) {
	return data_cache.GetOrCreate(path, func(path string) (string, error) {
		ans, err := os.ReadFile(path)
		return utils.UnsafeBytesToString(ans), err
	})
}

func size_for_path(path string) (int64, error) {
	return size_cache.GetOrCreate(path, func(path string) (int64, error) {
		s, err := os.Stat(path)
		if err != nil {
			return 0, err
		}
		return s.Size(), nil
	})
}

func is_image(path string) bool {
	return strings.HasPrefix(mimetype_for_path(path), "image/")
}

func is_path_text(path string) bool {
	return is_text_cache.MustGetOrCreate(path, func(path string) bool {
		if is_image(path) {
			return false
		}
		s1, err := os.Stat(path)
		if err == nil {
			s2, err := os.Stat("/dev/null")
			if err == nil && os.SameFile(s1, s2) {
				return false
			}
		}
		d, err := data_for_path(path)
		if err != nil {
			return false
		}
		return utf8.ValidString(d)
	})
}

func hash_for_path(path string) (string, error) {
	return hash_cache.GetOrCreate(path, func(path string) (string, error) {
		ans, err := data_for_path(path)
		if err != nil {
			return "", err
		}
		hash := md5.Sum(utils.UnsafeStringToBytes(ans))
		return utils.UnsafeBytesToString(hash[:]), err
	})

}

func text_to_lines(text string) []string {
	lines := make([]string, 0, 512)
	splitlines_like_git(text, false, func(line string) { lines = append(lines, line) })
	return lines
}

func sanitize(text string) string { return utils.ReplaceControlCodes(text, conf.Replace_tab_by, "\n") }

func lines_for_path(path string) ([]string, error) {
	return lines_cache.GetOrCreate(path, func(path string) ([]string, error) {
		ans, err := data_for_path(path)
		if err != nil {
			return nil, err
		}
		return text_to_lines(sanitize(ans)), nil
	})
}

func highlighted_lines_for_path(path string) ([]string, error) {
	plain_lines, err := lines_for_path(path)
	if err != nil {
		return nil, err
	}
	var ans []string
	var found bool
	if use_light_colors {
		ans, found = light_highlighted_lines_cache.Get(path)
	} else {
		ans, found = dark_highlighted_lines_cache.Get(path)
	}
	if found && len(ans) == len(plain_lines) {
		return ans, nil
	}
	return plain_lines, nil
}

type Collection struct {
	changes, renames, type_map map[string]string
	adds, removes              *utils.Set[string]
	all_paths                  []string
	paths_to_highlight         *utils.Set[string]
	added_count, removed_count int
}

func (self *Collection) add_change(left, right string) {
	self.changes[left] = right
	self.all_paths = append(self.all_paths, left)
	self.paths_to_highlight.Add(left)
	self.paths_to_highlight.Add(right)
	self.type_map[left] = `diff`
}

func (self *Collection) add_rename(left, right string) {
	self.renames[left] = right
	self.all_paths = append(self.all_paths, left)
	self.type_map[left] = `rename`
}

func (self *Collection) add_add(right string) {
	self.adds.Add(right)
	self.all_paths = append(self.all_paths, right)
	self.paths_to_highlight.Add(right)
	self.type_map[right] = `add`
	if is_path_text(right) {
		num, _ := lines_for_path(right)
		self.added_count += len(num)
	}
}

func (self *Collection) add_removal(left string) {
	self.removes.Add(left)
	self.all_paths = append(self.all_paths, left)
	self.paths_to_highlight.Add(left)
	self.type_map[left] = `removal`
	if is_path_text(left) {
		num, _ := lines_for_path(left)
		self.removed_count += len(num)
	}
}

func (self *Collection) finalize() {
	utils.StableSortWithKey(self.all_paths, func(path string) string {
		return path_name_map[path]
	})
}

func (self *Collection) Len() int { return len(self.all_paths) }

func (self *Collection) Items() int { return len(self.all_paths) }

func (self *Collection) Apply(f func(path, typ, changed_path string) error) error {
	for _, path := range self.all_paths {
		typ := self.type_map[path]
		changed_path := ""
		switch typ {
		case "diff":
			changed_path = self.changes[path]
		case "rename":
			changed_path = self.renames[path]
		}
		if err := f(path, typ, changed_path); err != nil {
			return err
		}
	}
	return nil
}

func allowed(path string, patterns ...string) bool {
	name := filepath.Base(path)
	for _, pat := range patterns {
		if matched, err := filepath.Match(pat, name); err == nil && matched {
			return false
		}
	}
	return true
}

func remote_hostname(path string) (string, string) {
	for q, val := range remote_dirs {
		if strings.HasPrefix(path, q) {
			return q, val
		}
	}
	return "", ""
}

func resolve_remote_name(path, defval string) string {
	remote_dir, rh := remote_hostname(path)
	if remote_dir != "" && rh != "" {
		r, err := filepath.Rel(remote_dir, path)
		if err == nil {
			return rh + ":" + r
		}
	}
	return defval
}

func walk(base string, patterns []string, names *utils.Set[string], pmap, path_name_map map[string]string) error {
	base, err := filepath.Abs(base)
	if err != nil {
		return err
	}
	return filepath.WalkDir(base, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		is_allowed := allowed(path, patterns...)
		if !is_allowed {
			if d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		if d.IsDir() {
			return nil
		}
		path, err = filepath.Abs(path)
		if err != nil {
			return err
		}
		name, err := filepath.Rel(base, path)
		if err != nil {
			return err
		}
		if name != "." {
			path_name_map[path] = name
			names.Add(name)
			pmap[name] = path
		}
		return nil
	})
}

func (self *Collection) collect_files(left, right string) error {
	left_names, right_names := utils.NewSet[string](16), utils.NewSet[string](16)
	left_path_map, right_path_map := make(map[string]string, 16), make(map[string]string, 16)
	err := walk(left, conf.Ignore_name, left_names, left_path_map, path_name_map)
	if err != nil {
		return err
	}
	if err = walk(right, conf.Ignore_name, right_names, right_path_map, path_name_map); err != nil {
		return err
	}
	common_names := left_names.Intersect(right_names)
	changed_names := utils.NewSet[string](common_names.Len())
	for n := range common_names.Iterable() {
		ld, err := data_for_path(left_path_map[n])
		var rd string
		if err == nil {
			rd, err = data_for_path(right_path_map[n])
		}
		if err != nil {
			return err
		}
		if ld != rd {
			changed_names.Add(n)
			self.add_change(left_path_map[n], right_path_map[n])
		} else {
			if lstat, err := os.Stat(left_path_map[n]); err == nil {
				if rstat, err := os.Stat(right_path_map[n]); err == nil {
					if lstat.Mode() != rstat.Mode() {
						// identical files with only a mode change
						changed_names.Add(n)
						self.add_change(left_path_map[n], right_path_map[n])
					}
				}
			}
		}
	}
	removed := left_names.Subtract(common_names)
	added := right_names.Subtract(common_names)
	ahash, rhash := make(map[string]string, added.Len()), make(map[string]string, removed.Len())
	for a := range added.Iterable() {
		ahash[a], err = hash_for_path(right_path_map[a])
		if err != nil {
			return err
		}
	}
	for r := range removed.Iterable() {
		rhash[r], err = hash_for_path(left_path_map[r])
		if err != nil {
			return err
		}
	}
	for name, rh := range rhash {
		found := false
		for n, ah := range ahash {
			if ah == rh {
				ld, _ := data_for_path(left_path_map[name])
				rd, _ := data_for_path(right_path_map[n])
				if ld == rd {
					self.add_rename(left_path_map[name], right_path_map[n])
					added.Discard(n)
					found = true
					break
				}
			}
		}
		if !found {
			self.add_removal(left_path_map[name])
		}
	}
	for name := range added.Iterable() {
		self.add_add(right_path_map[name])
	}
	return nil
}

func create_collection(left, right string) (ans *Collection, err error) {
	ans = &Collection{
		changes:            make(map[string]string),
		renames:            make(map[string]string),
		type_map:           make(map[string]string),
		adds:               utils.NewSet[string](32),
		removes:            utils.NewSet[string](32),
		paths_to_highlight: utils.NewSet[string](32),
		all_paths:          make([]string, 0, 32),
	}
	left_stat, err := os.Stat(left)
	if err != nil {
		return nil, err
	}
	if left_stat.IsDir() {
		err = ans.collect_files(left, right)
		if err != nil {
			return nil, err
		}
	} else {
		pl, err := filepath.Abs(left)
		if err != nil {
			return nil, err
		}
		pr, err := filepath.Abs(right)
		if err != nil {
			return nil, err
		}
		path_name_map[pl] = resolve_remote_name(pl, left)
		path_name_map[pr] = resolve_remote_name(pr, right)
		ans.add_change(pl, pr)
	}
	ans.finalize()
	return ans, err
}
