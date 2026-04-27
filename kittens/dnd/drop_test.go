// License: GPLv3 Copyright: 2025, Kovid Goyal, <kovid at kovidgoyal.net>

package dnd

import (
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// openDir opens a directory for use as an *os.File, closing it on test cleanup.
func openDir(t *testing.T, path string) *os.File {
	t.Helper()
	d, err := os.Open(path)
	if err != nil {
		t.Fatalf("openDir %s: %v", path, err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

// buildTree creates a directory tree described by a map of relative path ->
// content. A nil content value creates a directory; a non-nil value (even
// empty string) creates a regular file. Symlink entries are expressed via the
// separate symlinks map: relative link name -> target string.
func buildTree(t *testing.T, base string, files map[string]string, symlinks map[string]string) {
	t.Helper()
	for rel, content := range files {
		full := filepath.Join(base, rel)
		if content == "" && files[rel] == "" {
			// Create parent dirs in case they are missing.
			if err := os.MkdirAll(filepath.Dir(full), 0755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(full, []byte(content), 0644); err != nil {
				t.Fatal(err)
			}
		} else {
			if err := os.MkdirAll(filepath.Dir(full), 0755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(full, []byte(content), 0644); err != nil {
				t.Fatal(err)
			}
		}
	}
	for name, target := range symlinks {
		full := filepath.Join(base, name)
		if err := os.MkdirAll(filepath.Dir(full), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(target, full); err != nil {
			t.Fatal(err)
		}
	}
}

// sortedStrings returns a sorted copy of the slice.
func sortedStrings(s []string) []string {
	out := append([]string(nil), s...)
	sort.Strings(out)
	return out
}

// TestFindOverwrites_NoOverlap verifies that an empty result is returned when
// source and destination have no names in common.
func TestFindOverwrites_NoOverlap(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	buildTree(t, src, map[string]string{"a.txt": "a", "b.txt": "b"}, nil)
	buildTree(t, dst, map[string]string{"c.txt": "c"}, nil)

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	got, err := find_overwrites(srcDir, dstDir)
	if err != nil {
		t.Fatalf("find_overwrites: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("expected no overwrites, got %v", got)
	}
}

// TestFindOverwrites_FileOverlap verifies that files existing in both trees
// are reported.
func TestFindOverwrites_FileOverlap(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	buildTree(t, src, map[string]string{"shared.txt": "src", "only_src.txt": "x"}, nil)
	buildTree(t, dst, map[string]string{"shared.txt": "dst", "only_dst.txt": "y"}, nil)

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	got, err := find_overwrites(srcDir, dstDir)
	if err != nil {
		t.Fatalf("find_overwrites: %v", err)
	}
	if len(got) != 1 || got[0] != "shared.txt" {
		t.Errorf("expected [shared.txt], got %v", got)
	}
}

// TestFindOverwrites_DirsNotReported verifies that matching *directories* in
// both trees are not reported as overwrites — only non-directory conflicts are.
func TestFindOverwrites_DirsNotReported(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	// Both have "subdir/" — it should NOT appear in the overwrite list.
	os.MkdirAll(filepath.Join(src, "subdir"), 0755)
	os.MkdirAll(filepath.Join(dst, "subdir"), 0755)
	buildTree(t, src, map[string]string{"subdir/file.txt": "s"}, nil)
	buildTree(t, dst, map[string]string{"subdir/file.txt": "d"}, nil)

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	got, err := find_overwrites(srcDir, dstDir)
	if err != nil {
		t.Fatalf("find_overwrites: %v", err)
	}
	// Only the nested file should be reported, not "subdir".
	if len(got) != 1 || got[0] != "subdir/file.txt" {
		t.Errorf("expected [subdir/file.txt], got %v", got)
	}
}

// TestFindOverwrites_NestedTree tests a multi-level tree with a mix of
// regular files, nested directories, and symlinks.
func TestFindOverwrites_NestedTree(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)

	// src layout:
	//   top.txt          (overwrite — exists in dst too)
	//   only_src.txt
	//   sub/
	//     nested.txt     (overwrite)
	//     deep/
	//       file.txt     (overwrite)
	//   link -> target   (symlink overwrite)
	os.MkdirAll(filepath.Join(src, "sub", "deep"), 0755)
	buildTree(t, src, map[string]string{
		"top.txt":           "src",
		"only_src.txt":      "x",
		"sub/nested.txt":    "src",
		"sub/deep/file.txt": "src",
	}, map[string]string{"link": "target"})

	// dst layout:
	//   top.txt          (shared file)
	//   only_dst.txt
	//   sub/
	//     nested.txt     (shared file)
	//     deep/
	//       file.txt     (shared file)
	//   link -> other    (symlink — same name, different target)
	os.MkdirAll(filepath.Join(dst, "sub", "deep"), 0755)
	buildTree(t, dst, map[string]string{
		"top.txt":           "dst",
		"only_dst.txt":      "y",
		"sub/nested.txt":    "dst",
		"sub/deep/file.txt": "dst",
	}, map[string]string{"link": "other"})

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	got, err := find_overwrites(srcDir, dstDir)
	if err != nil {
		t.Fatalf("find_overwrites: %v", err)
	}
	want := []string{"link", "sub/deep/file.txt", "sub/nested.txt", "top.txt"}
	if got2 := sortedStrings(got); !equalStringSlices(got2, want) {
		t.Errorf("find_overwrites: got %v, want %v", got2, want)
	}
}

// TestFindOverwrites_SymlinksTransferredAsIs verifies that a symlink in the
// source with the same name as a symlink in the destination is reported as an
// overwrite regardless of the symlink targets, and that symlinks are not
// followed.
func TestFindOverwrites_SymlinksTransferredAsIs(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	// Both have a symlink named "link" pointing to different targets.
	os.Symlink("target_a", filepath.Join(src, "link"))
	os.Symlink("target_b", filepath.Join(dst, "link"))

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	got, err := find_overwrites(srcDir, dstDir)
	if err != nil {
		t.Fatalf("find_overwrites: %v", err)
	}
	if len(got) != 1 || got[0] != "link" {
		t.Errorf("expected [link], got %v", got)
	}
}

// TestFindOverwrites_DirVsFile reports the case where src has a directory and
// dst has a file with the same name (or vice versa).
func TestFindOverwrites_DirVsFile(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	// src has a directory named "conflict"; dst has a regular file with the same name.
	os.MkdirAll(filepath.Join(src, "conflict"), 0755)
	os.WriteFile(filepath.Join(dst, "conflict"), []byte("file"), 0644)

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	got, err := find_overwrites(srcDir, dstDir)
	if err != nil {
		t.Fatalf("find_overwrites: %v", err)
	}
	// A directory in src vs a file in dst should be reported.
	if len(got) != 1 || got[0] != "conflict" {
		t.Errorf("expected [conflict], got %v", got)
	}
}

// --- rename_contents tests ---

// TestRenameContents_SimpleFiles verifies that plain files are moved from src
// to dst.
func TestRenameContents_SimpleFiles(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	buildTree(t, src, map[string]string{"a.txt": "aaa", "b.txt": "bbb"}, nil)

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	if err := rename_contents(srcDir, dstDir); err != nil {
		t.Fatalf("rename_contents: %v", err)
	}

	for _, name := range []string{"a.txt", "b.txt"} {
		if _, err := os.Stat(filepath.Join(src, name)); !os.IsNotExist(err) {
			t.Errorf("%s should have been moved out of src", name)
		}
		if _, err := os.Stat(filepath.Join(dst, name)); err != nil {
			t.Errorf("%s should exist in dst: %v", name, err)
		}
	}
}

// TestRenameContents_MergesNestedDirs verifies that when both src and dst
// already have a subdirectory with the same name, their contents are merged
// recursively.
func TestRenameContents_MergesNestedDirs(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(filepath.Join(src, "sub"), 0755)
	os.MkdirAll(filepath.Join(dst, "sub"), 0755)
	buildTree(t, src, map[string]string{
		"sub/from_src.txt": "src",
	}, nil)
	buildTree(t, dst, map[string]string{
		"sub/from_dst.txt": "dst",
	}, nil)

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	if err := rename_contents(srcDir, dstDir); err != nil {
		t.Fatalf("rename_contents: %v", err)
	}

	// Both files must now live under dst/sub/.
	for _, name := range []string{"from_src.txt", "from_dst.txt"} {
		if _, err := os.Stat(filepath.Join(dst, "sub", name)); err != nil {
			t.Errorf("dst/sub/%s missing: %v", name, err)
		}
	}
}

// TestRenameContents_NestedMultiLevel verifies correct merging across multiple
// nesting levels.
func TestRenameContents_NestedMultiLevel(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")

	// Build a 3-level nested source tree.
	os.MkdirAll(filepath.Join(src, "a", "b"), 0755)
	os.MkdirAll(filepath.Join(dst, "a", "b"), 0755)
	buildTree(t, src, map[string]string{
		"top.txt":      "top",
		"a/mid.txt":    "mid",
		"a/b/deep.txt": "deep",
	}, nil)
	buildTree(t, dst, map[string]string{
		"a/existing.txt": "existing",
	}, nil)

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	if err := rename_contents(srcDir, dstDir); err != nil {
		t.Fatalf("rename_contents: %v", err)
	}

	expected := []string{"top.txt", "a/mid.txt", "a/b/deep.txt", "a/existing.txt"}
	for _, rel := range expected {
		if _, err := os.Stat(filepath.Join(dst, rel)); err != nil {
			t.Errorf("dst/%s missing: %v", rel, err)
		}
	}
}

// TestRenameContents_SymlinksMovedAsIs verifies that symlinks are moved as-is
// (not followed), preserving both the link and its original target string.
func TestRenameContents_SymlinksMovedAsIs(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	// A symlink pointing to a non-existent target — if followed it would fail.
	os.Symlink("does_not_exist", filepath.Join(src, "link"))

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	if err := rename_contents(srcDir, dstDir); err != nil {
		t.Fatalf("rename_contents: %v", err)
	}

	// Symlink must have arrived in dst.
	target, err := os.Readlink(filepath.Join(dst, "link"))
	if err != nil {
		t.Fatalf("readlink dst/link: %v", err)
	}
	if target != "does_not_exist" {
		t.Errorf("symlink target: got %q, want %q", target, "does_not_exist")
	}
	// Must no longer be in src.
	if _, err := os.Lstat(filepath.Join(src, "link")); !os.IsNotExist(err) {
		t.Error("link should have been moved out of src")
	}
}

// TestRenameContents_SymlinksInSubdirMovedAsIs checks that symlinks inside a
// nested directory are also moved without following.
func TestRenameContents_SymlinksInSubdirMovedAsIs(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(filepath.Join(src, "sub"), 0755)
	os.MkdirAll(filepath.Join(dst, "sub"), 0755)
	os.WriteFile(filepath.Join(src, "sub", "file.txt"), []byte("data"), 0644)
	// Symlink with an absolute target to ensure it is not resolved.
	os.Symlink("/absolute/path", filepath.Join(src, "sub", "abslink"))

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	if err := rename_contents(srcDir, dstDir); err != nil {
		t.Fatalf("rename_contents: %v", err)
	}

	target, err := os.Readlink(filepath.Join(dst, "sub", "abslink"))
	if err != nil {
		t.Fatalf("readlink dst/sub/abslink: %v", err)
	}
	if target != "/absolute/path" {
		t.Errorf("symlink target: got %q, want %q", target, "/absolute/path")
	}
}

// TestRenameContents_DirExistsInDest verifies that directories already
// existing in dest are not treated as overwrites — their contents are merged
// and no error is returned.
func TestRenameContents_DirExistsInDest(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(filepath.Join(src, "shared"), 0755)
	os.MkdirAll(filepath.Join(dst, "shared"), 0755)
	buildTree(t, src, map[string]string{"shared/new.txt": "new"}, nil)
	buildTree(t, dst, map[string]string{"shared/old.txt": "old"}, nil)

	srcDir := openDir(t, src)
	dstDir := openDir(t, dst)

	if err := rename_contents(srcDir, dstDir); err != nil {
		t.Fatalf("rename_contents should succeed when dir exists in dest: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dst, "shared", "new.txt")); err != nil {
		t.Errorf("dst/shared/new.txt missing: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dst, "shared", "old.txt")); err != nil {
		t.Errorf("dst/shared/old.txt missing: %v", err)
	}
}

// equalStringSlices returns true when two sorted slices are equal.
func equalStringSlices(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
