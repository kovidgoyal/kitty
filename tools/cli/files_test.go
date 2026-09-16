// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/utils"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"
)

var _ = fmt.Print

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
		CompleteFiles(prefix, func(entry *FileEntry) {
			actual = append(actual, entry.CompletionCandidate)
			if _, err := os.Stat(entry.Abspath); err != nil {
				t.Fatalf("Abspath does not exist: %#v", entry.Abspath)
			}
		}, "")
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
				if strings.HasSuffix(x, utils.Sep) {
					e[i] += utils.Sep
				}
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

	test_cwd_prefix("", "one.txt", "two.txt", "odir/")
	test_cwd_prefix("t", "two.txt")
	test_cwd_prefix("x")

	test_abs_candidates(tdir+utils.Sep, "one.txt", "two.txt", "odir/")
	test_abs_candidates(filepath.Join(tdir, "o"), "one.txt", "odir/")

	test_candidates("", "one.txt", "two.txt", "odir/")
	test_candidates("t", "two.txt")
	test_candidates("o", "one.txt", "odir/")
	test_candidates("odir", "odir/")
	test_candidates("odir/", "odir/three.txt", "odir/four.txt")
	test_candidates("odir/f", "odir/four.txt")
	test_candidates("x")

	// a prefix whose only separator is the leading one, such as /us
	if entries, err := os.ReadDir(utils.Sep); err == nil && len(entries) > 0 {
		name := entries[0].Name()
		prefix := utils.Sep + name[:1]
		found := false
		CompleteFiles(prefix, func(entry *FileEntry) {
			found = found || strings.TrimSuffix(entry.CompletionCandidate, utils.Sep) == utils.Sep+name
		}, "")
		if !found {
			t.Fatalf("Did not get %#v as a completion candidate for prefix: %#v", utils.Sep+name, prefix)
		}
	}

	// symlinks to directories are directories
	os.Symlink(filepath.Join(tdir, "odir"), filepath.Join(tdir, "slink"))
	c := NewCompletions()
	DirectoryCompleter("", CWD)(c, "s", 0)
	if len(c.Groups) != 1 || len(c.Groups[0].Matches) != 1 || c.Groups[0].Matches[0].Word != "slink/" {
		t.Fatalf("Symlink to directory not completed by DirectoryCompleter: %#v", c.Groups)
	}

	// filenames inside a directory are matched case-insensitively against patterns
	os.Mkdir(filepath.Join(tdir, "cdir"), 0700)
	create("cdir", "B.CONF")
	c = NewCompletions()
	FnmatchCompleter("", CWD, "*.conf")(c, "c", 0)
	found := false
	for _, g := range c.Groups {
		for _, m := range g.Matches {
			found = found || m.Word == "cdir/"
		}
	}
	if !found {
		t.Fatalf("Directory containing only an uppercase extension match not completed by FnmatchCompleter: %#v", c.Groups)
	}

	// mime types kitty knows about but the Go stdlib does not
	create("zz.py")
	c = NewCompletions()
	MimepatCompleter("", CWD, "text/*")(c, "zz", 0)
	found = false
	for _, g := range c.Groups {
		for _, m := range g.Matches {
			found = found || m.Word == "zz.py"
		}
	}
	if !found {
		t.Fatalf("File with a mime type known only to kitty not completed by MimepatCompleter: %#v", c.Groups)
	}
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
		actual := CompleteExecutablesInPath(prefix)
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
