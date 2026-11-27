// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"unicode/utf8"
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

func TestAtomicTempName(t *testing.T) {
	dir := t.TempDir()
	for _, base := range []string{"short", strings.Repeat("a", 255), strings.Repeat("a", 31) + "é" + strings.Repeat("b", 200)} {
		name := atomic_temp_name(filepath.Join(dir, base))
		if filepath.Dir(name) != dir {
			t.Fatalf("Temp name %q not in the destination directory", name)
		}
		b := filepath.Base(name)
		if len(b) > 64 || !utf8.ValidString(b) || !strings.HasPrefix(b, "."+base[:min(len(base), 5)]) {
			t.Fatalf("Unexpected temp name: %q", b)
		}
	}
}

func TestAtomicCreateLinkErrors(t *testing.T) {
	for _, hardlink := range []bool{false, true} {
		dir := t.TempDir()
		target, dest := filepath.Join(dir, "target"), filepath.Join(dir, "dest")
		if err := os.WriteFile(target, nil, 0o644); err != nil {
			t.Fatal(err)
		}
		if err := os.MkdirAll(filepath.Join(dest, "child"), 0o755); err != nil {
			t.Fatal(err)
		}
		var err error
		if hardlink {
			err = AtomicCreateHardlink(target, dest)
		} else {
			err = AtomicCreateSymlink(target, dest)
		}
		if !errors.Is(err, syscall.EISDIR) || !strings.Contains(err.Error(), dest) {
			t.Fatalf("Unexpected error replacing a directory with a link: %v", err)
		}
		if entries, err := os.ReadDir(dir); err != nil || len(entries) != 2 {
			t.Fatalf("Stray files left behind after failed link: %v %v", entries, err)
		}
	}
}
