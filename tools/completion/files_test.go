// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"
)

func TestCompleteFiles(t *testing.T) {
	tdir := t.TempDir()
	cwd, _ := os.Getwd()
	if cwd != "" {
		defer os.Chdir(cwd)
	}
	os.Chdir(tdir)

	create := func(parts ...string) {
		f, _ := os.Create(filepath.Join(tdir, filepath.Join(parts...)))
		f.Close()
	}
	create("one.txt")
	create("two.txt")
	os.Mkdir(filepath.Join(tdir, "odir"), 0700)
	create("odir", "three.txt")
	create("odir", "four.txt")

	test_candidates := func(prefix string, expected ...string) {
		if expected == nil {
			expected = make([]string, 0)
		}
		sort.Strings(expected)
		actual := make([]string, 0, len(expected))
		complete_files(prefix, func(completion_candidate string, abspath string, d fs.DirEntry) error {
			actual = append(actual, completion_candidate)
			if _, err := os.Stat(abspath); err != nil {
				t.Fatalf("Abspath does not exist: %#v", abspath)
				return fmt.Errorf("abspath does not exist")
			}
			return nil
		})
		sort.Strings(actual)
		if !reflect.DeepEqual(expected, actual) {
			t.Fatalf("Did not get expected completion candidates for prefix: %#v\nExpected: %#v\nActual:   %#v", prefix, expected, actual)
		}
	}

	test_abs_candidates := func(prefix string, expected ...string) {
		e := make([]string, len(expected))
		for i, x := range expected {
			if filepath.IsAbs(x) {
				e[i] = x
			} else {
				e[i] = filepath.Join(tdir, x)
			}
		}
		test_candidates(prefix, e...)
	}

	test_cwd_prefix := func(prefix string, expected ...string) {
		e := make([]string, len(expected))
		for i, x := range expected {
			e[i] = "./" + x
		}
		test_candidates("./"+prefix, e...)
	}

	test_cwd_prefix("", "one.txt", "two.txt", "odir", "odir/three.txt", "odir/four.txt")
	test_cwd_prefix("t", "two.txt")
	test_cwd_prefix("x")

	test_abs_candidates(tdir, tdir, "one.txt", "two.txt", "odir", "odir/three.txt", "odir/four.txt")
	test_abs_candidates(filepath.Join(tdir, "o"), "one.txt", "odir", "odir/three.txt", "odir/four.txt")

	test_candidates("", "one.txt", "two.txt", "odir", "odir/three.txt", "odir/four.txt")
	test_candidates("t", "two.txt")
	test_candidates("o", "one.txt", "odir", "odir/three.txt", "odir/four.txt")
	test_candidates("odir", "odir", "odir/three.txt", "odir/four.txt")
	test_candidates("odir/", "odir/three.txt", "odir/four.txt")
	test_candidates("odir/f", "odir/four.txt")
	test_candidates("x")

}

func TestCompleteExecutables(t *testing.T) {
	tdir := t.TempDir()
	create := func(base string, name string, mode os.FileMode) {
		f, _ := os.OpenFile(filepath.Join(tdir, base, name), os.O_CREATE, mode)
		f.Close()
	}
	os.Mkdir(filepath.Join(tdir, "one"), 0700)
	os.Mkdir(filepath.Join(tdir, "two"), 0700)

	create("", "not-in-path", 0700)
	create("one", "one-exec", 0700)
	create("one", "one-not-exec", 0600)
	create("two", "two-exec", 0700)
	os.Symlink(filepath.Join(tdir, "two", "two-exec"), filepath.Join(tdir, "one", "s"))
	os.Symlink(filepath.Join(tdir, "one", "one-not-exec"), filepath.Join(tdir, "one", "n"))

	t.Setenv("PATH", strings.Join([]string{filepath.Join(tdir, "one"), filepath.Join(tdir, "two")}, string(os.PathListSeparator)))
	test_candidates := func(prefix string, expected ...string) {
		if expected == nil {
			expected = make([]string, 0)
		}
		actual := complete_executables_in_path(prefix)
		sort.Strings(expected)
		sort.Strings(actual)
		if !reflect.DeepEqual(expected, actual) {
			t.Fatalf("Did not get expected completion candidates for prefix: %#v\nExpected: %#v\nActual:   %#v", prefix, expected, actual)
		}
	}
	test_candidates("", "one-exec", "two-exec", "s")
	test_candidates("o", "one-exec")
	test_candidates("x")
}
