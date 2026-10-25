// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAtomicWriteFileSymlinkChain(t *testing.T) {
	dir := t.TempDir()
	t.Chdir(dir)
	for _, name := range []string{"nested", "real"} {
		if err := os.Mkdir(name, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	// nested/link -> link -> parent/target where parent -> real and real/target does not exist
	links := []struct{ path, target string }{{"nested/link", "../link"}, {"link", "parent/target"}, {"parent", "real"}}
	for _, l := range links {
		if err := os.Symlink(l.target, l.path); err != nil {
			t.Fatal(err)
		}
	}
	if err := AtomicWriteFile(filepath.Join("nested", "link"), strings.NewReader("new contents"), 0o640); err != nil {
		t.Fatal(err)
	}
	for _, l := range links {
		if actual, err := os.Readlink(l.path); err != nil || actual != l.target {
			t.Errorf("Symlink %s changed: %q %v", l.path, actual, err)
		}
	}
	target := filepath.Join("real", "target")
	assert_file_contents(t, target, "new contents")
	if st, err := os.Stat(target); err != nil || st.Mode().Perm() != 0o640 {
		t.Fatalf("Incorrect target permissions: %v %v", st, err)
	}
	if entries, err := os.ReadDir("real"); err != nil || len(entries) != 1 || entries[0].Name() != "target" {
		t.Fatalf("Stray files left behind after write: %v %v", entries, err)
	}
}

func TestAtomicWriteFileSymlinkFailure(t *testing.T) {
	for _, link := range []string{"missing/target", "link"} {
		t.Run(link, func(t *testing.T) {
			dir := t.TempDir()
			dest := filepath.Join(dir, "link")
			if err := os.Symlink(link, dest); err != nil {
				t.Fatal(err)
			}
			if err := AtomicWriteFile(dest, strings.NewReader("new contents"), 0o600); err == nil {
				t.Error("Expected write to fail with a missing parent directory or a symlink loop")
			}
			if actual, err := os.Readlink(dest); err != nil || actual != link {
				t.Errorf("Symlink at destination changed: %q %v", actual, err)
			}
			if entries, err := os.ReadDir(dir); err != nil || len(entries) != 1 || entries[0].Name() != "link" {
				t.Fatalf("Stray files left behind after failed write: %v %v", entries, err)
			}
		})
	}
}
