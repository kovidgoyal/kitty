// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"os"
	"path/filepath"
)

var _ = fmt.Print
var path_name_map, remote_dirs map[string]string

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
