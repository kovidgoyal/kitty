// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestPathMappingSend(t *testing.T) {
	opts := &Options{}
	tdir := t.TempDir()
	b := filepath.Join(tdir, "b")
	os.Mkdir(b, 0o700)
	os.WriteFile(filepath.Join(b, "r"), nil, 0600)
	os.Mkdir(filepath.Join(b, "d"), 0o700)
	os.WriteFile(filepath.Join(b, "d", "r"), nil, 0600)

	gm := func(args ...string) ([]*File, error) {
		return files_for_send(opts, args)
	}

	mp := func(path string, is_remote bool) string {
		path = strings.TrimSpace(path)
		if strings.HasPrefix(path, "~") || filepath.IsAbs(path) {
			return path
		}
		return filepath.Join(tdir, path)
	}

	tf := func(expected string, args ...string) {
		files, err := gm(args...)
		if err != nil {
			t.Fatalf("Failed with mode: %s cwd: %s home: %s and args: %#v\n%s", opts.Mode, cwd_path(), home_path(), args, err)
		}
		actual := make(map[string]string)
		for _, f := range files {
			actual[f.expanded_local_path] = f.remote_path
		}
		e := make(map[string]string, len(actual))
		for _, rec := range strings.Split(expected, " ") {
			k, v, _ := strings.Cut(rec, ":")
			e[mp(k, false)] = mp(v, true)
		}
		if diff := cmp.Diff(e, actual); diff != "" {
			t.Fatalf("Failed with mode: %s cwd: %s home: %s and args: %#v\n%s", opts.Mode, cwd_path(), home_path(), args, diff)
		}
	}

	opts.Mode = "mirror"
	run_with_paths(b, "/foo/bar", func() {
		tf("b/r:b/r b/d:b/d b/d/r:b/d/r", "r", "d")
		tf("b/r:b/r b/d/r:b/d/r", "r", "d/r")
	})
	run_with_paths(b, tdir, func() {
		tf("b/r:~/b/r b/d:~/b/d b/d/r:~/b/d/r", "r", "d")
	})
	opts.Mode = "normal"
	run_with_paths("/some/else", "/foo/bar", func() {
		tf("b/r:/dest/r b/d:/dest/d b/d/r:/dest/d/r", filepath.Join(b, "r"), filepath.Join(b, "d"), "/dest")
		tf("b/r:~/dest/r b/d:~/dest/d b/d/r:~/dest/d/r", filepath.Join(b, "r"), filepath.Join(b, "d"), "~/dest")
	})
	run_with_paths(b, "/foo/bar", func() {
		tf("b/r:/dest/r b/d:/dest/d b/d/r:/dest/d/r", "r", "d", "/dest")
	})
	os.Symlink("/foo/b", filepath.Join(b, "e"))
	os.Symlink("r", filepath.Join(b, "s"))
	os.Link(filepath.Join(b, "r"), filepath.Join(b, "h"))

	file_idx := 0
	first_file := func(args ...string) *File {
		files, err := gm(args...)
		if err != nil {
			t.Fatal(err)
		}
		return files[file_idx]
	}
	ae := func(a any, b any) {
		if diff := cmp.Diff(a, b); diff != "" {
			t.Fatalf("%s", diff)
		}
	}
	run_with_paths("/some/else", "/foo/bar", func() {
		f := first_file(filepath.Join(b, "e"), "dest")
		ae(f.symbolic_link_target, "path:/foo/b")
		f = first_file(filepath.Join(b, "s"), filepath.Join(b, "r"), "dest")
		ae(f.symbolic_link_target, "fid:2")
		f = first_file(filepath.Join(b, "h"), "dest")
		ae(f.file_type, FileType_regular)
		file_idx = 1
		f = first_file(filepath.Join(b, "h"), filepath.Join(b, "r"), "dest")
		ae(f.hard_link_target, "fid:1")
		ae(f.file_type, FileType_link)
	})
}
