// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"kitty/tools/utils"
	"os"
	"path/filepath"
	"strings"
)

var _ = fmt.Print
var path_name_map, remote_dirs map[string]string

var mimetypes_cache, data_cache *utils.LRUCache[string, string]
var lines_cache *utils.LRUCache[string, []string]

func init_caches() {
	mimetypes_cache = utils.NewLRUCache[string, string](4096)
	data_cache = utils.NewLRUCache[string, string](4096)
	lines_cache = utils.NewLRUCache[string, []string](4096)
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

func sanitize(x string) string {
	x = strings.ReplaceAll(x, "\r\n", "⏎\n")
	return utils.SanitizeControlCodes(x, "░")
}

func lines_for_path(path string) ([]string, error) {
	return lines_cache.GetOrCreate(path, func(path string) ([]string, error) {
		ans, err := data_for_path(path)
		if err != nil {
			return nil, err
		}
		ans = sanitize(strings.ReplaceAll(ans, "\t", conf.Replace_tab_by))
		lines := make([]string, 0, 256)
		splitlines_like_git(ans, false, func(line string) { lines = append(lines, line) })
		return lines, nil
	})
}

type Collection struct {
}

func create_collection(left, right string) (ans *Collection, err error) {
	path_name_map = make(map[string]string, 32)
	remote_dirs = make(map[string]string, 32)
	ans = &Collection{}
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
		err = ans.add_change(pl, pr)
		if err != nil {
			return nil, err
		}
	}
	err = ans.finalize()
	return ans, err
}
