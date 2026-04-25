// License: GPLv3 Copyright: 2025, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"context"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"syscall"
	"testing"
)

// openTestDir opens the directory at path for the test, closing it on cleanup.
func openTestDir(t *testing.T, path string) *os.File {
	t.Helper()
	d, err := os.Open(path)
	if err != nil {
		t.Fatalf("openTestDir %s: %v", path, err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

// mustReadFile returns the contents of path or fatals the test.
func mustReadFile(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile %s: %v", path, err)
	}
	return string(b)
}

// countOpenFDs returns the number of open file descriptors in the process.
// It uses /proc/self/fd and is only meaningful on Linux; returns -1 elsewhere.
func countOpenFDs() int {
	if runtime.GOOS != "linux" {
		return -1
	}
	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		return -1
	}
	return len(entries)
}

// --- Tests for individual API functions ---

func TestMkdirAt(t *testing.T) {
	tmp := t.TempDir()
	d := openTestDir(t, tmp)

	if err := MkdirAt(d, "newdir", 0755); err != nil {
		t.Fatalf("MkdirAt: %v", err)
	}
	info, err := os.Stat(filepath.Join(tmp, "newdir"))
	if err != nil {
		t.Fatalf("stat after MkdirAt: %v", err)
	}
	if !info.IsDir() {
		t.Error("expected a directory")
	}

	// Creating same directory again should return a PathError wrapping EEXIST.
	err = MkdirAt(d, "newdir", 0755)
	if err == nil {
		t.Fatal("expected error for duplicate MkdirAt")
	}
	var pe *fs.PathError
	if !errors.As(err, &pe) {
		t.Errorf("expected *fs.PathError, got %T: %v", err, err)
	}
}

func TestOpenAt(t *testing.T) {
	tmp := t.TempDir()
	os.WriteFile(filepath.Join(tmp, "hello.txt"), []byte("world"), 0644)
	d := openTestDir(t, tmp)

	f, err := OpenAt(d, "hello.txt")
	if err != nil {
		t.Fatalf("OpenAt: %v", err)
	}
	defer f.Close()

	buf := make([]byte, 5)
	n, _ := f.Read(buf)
	if got := string(buf[:n]); got != "world" {
		t.Errorf("OpenAt read: got %q, want %q", got, "world")
	}

	if _, err = OpenAt(d, "nonexistent.txt"); err == nil {
		t.Error("expected error for non-existent file")
	}
}

func TestOpenDirAt(t *testing.T) {
	tmp := t.TempDir()
	os.Mkdir(filepath.Join(tmp, "subdir"), 0755)
	os.WriteFile(filepath.Join(tmp, "file.txt"), []byte("x"), 0644)
	d := openTestDir(t, tmp)

	sub, err := OpenDirAt(d, "subdir")
	if err != nil {
		t.Fatalf("OpenDirAt: %v", err)
	}
	defer sub.Close()
	info, _ := sub.Stat()
	if !info.IsDir() {
		t.Error("OpenDirAt: expected directory")
	}

	// Opening a regular file as a directory should fail.
	if _, err = OpenDirAt(d, "file.txt"); err == nil {
		t.Error("expected error opening regular file as directory")
	}
}

func TestCreateAt(t *testing.T) {
	tmp := t.TempDir()
	d := openTestDir(t, tmp)

	f, err := CreateAt(d, "new.txt", 0644)
	if err != nil {
		t.Fatalf("CreateAt: %v", err)
	}
	f.WriteString("hello")
	f.Close()

	if got := mustReadFile(t, filepath.Join(tmp, "new.txt")); got != "hello" {
		t.Errorf("CreateAt content: got %q, want %q", got, "hello")
	}

	// CreateAt on an existing file should truncate it.
	f2, err := CreateAt(d, "new.txt", 0644)
	if err != nil {
		t.Fatalf("CreateAt (truncate): %v", err)
	}
	f2.WriteString("bye")
	f2.Close()

	if got := mustReadFile(t, filepath.Join(tmp, "new.txt")); got != "bye" {
		t.Errorf("CreateAt truncate: got %q, want %q", got, "bye")
	}
}

func TestCreateDirAt(t *testing.T) {
	tmp := t.TempDir()
	d := openTestDir(t, tmp)

	sub, err := CreateDirAt(d, "mydir", 0755)
	if err != nil {
		t.Fatalf("CreateDirAt new: %v", err)
	}
	sub.Close()

	// Should succeed when the directory already exists.
	sub2, err := CreateDirAt(d, "mydir", 0700)
	if err != nil {
		t.Fatalf("CreateDirAt existing: %v", err)
	}
	sub2.Close()
}

func TestSymlinkAt(t *testing.T) {
	tmp := t.TempDir()
	os.WriteFile(filepath.Join(tmp, "target.txt"), []byte("data"), 0644)
	d := openTestDir(t, tmp)

	if err := SymlinkAt(d, "link.txt", "target.txt"); err != nil {
		t.Fatalf("SymlinkAt: %v", err)
	}
	got, err := os.Readlink(filepath.Join(tmp, "link.txt"))
	if err != nil {
		t.Fatalf("Readlink: %v", err)
	}
	if got != "target.txt" {
		t.Errorf("symlink target: got %q, want %q", got, "target.txt")
	}

	// Duplicate symlink should fail.
	if err = SymlinkAt(d, "link.txt", "target.txt"); err == nil {
		t.Error("expected error for duplicate symlink")
	}
}

func TestStatAt(t *testing.T) {
	tmp := t.TempDir()
	os.WriteFile(filepath.Join(tmp, "file.txt"), []byte("content"), 0644)
	os.Symlink("file.txt", filepath.Join(tmp, "link.txt"))
	d := openTestDir(t, tmp)

	// StatAt follows symlinks.
	info, err := StatAt(d, "link.txt")
	if err != nil {
		t.Fatalf("StatAt: %v", err)
	}
	if info.Mode()&os.ModeSymlink != 0 {
		t.Error("StatAt should dereference symlinks")
	}
	if !info.Mode().IsRegular() {
		t.Error("StatAt: expected regular file after following symlink")
	}

	if _, err = StatAt(d, "nonexistent"); err == nil {
		t.Error("expected error for non-existent file")
	}
}

func TestLstatAt(t *testing.T) {
	tmp := t.TempDir()
	os.WriteFile(filepath.Join(tmp, "file.txt"), []byte("content"), 0644)
	os.Symlink("file.txt", filepath.Join(tmp, "link.txt"))
	d := openTestDir(t, tmp)

	// LstatAt must not follow symlinks.
	info, err := LstatAt(d, "link.txt")
	if err != nil {
		t.Fatalf("LstatAt symlink: %v", err)
	}
	if info.Mode()&os.ModeSymlink == 0 {
		t.Error("LstatAt should not dereference symlinks")
	}

	info2, err := LstatAt(d, "file.txt")
	if err != nil {
		t.Fatalf("LstatAt file: %v", err)
	}
	if !info2.Mode().IsRegular() {
		t.Error("LstatAt file: expected regular file")
	}
}

func TestUnlinkAt(t *testing.T) {
	tmp := t.TempDir()
	os.WriteFile(filepath.Join(tmp, "todelete.txt"), []byte("x"), 0644)
	d := openTestDir(t, tmp)

	if err := UnlinkAt(d, "todelete.txt"); err != nil {
		t.Fatalf("UnlinkAt: %v", err)
	}
	if _, err := os.Stat(filepath.Join(tmp, "todelete.txt")); !os.IsNotExist(err) {
		t.Error("file should be removed after UnlinkAt")
	}

	if err := UnlinkAt(d, "nonexistent"); err == nil {
		t.Error("expected error for non-existent file")
	}
}

func TestRemoveDirAt(t *testing.T) {
	tmp := t.TempDir()
	os.Mkdir(filepath.Join(tmp, "empty"), 0755)
	os.Mkdir(filepath.Join(tmp, "nonempty"), 0755)
	os.WriteFile(filepath.Join(tmp, "nonempty", "f"), []byte(""), 0644)
	d := openTestDir(t, tmp)

	if err := RemoveDirAt(d, "empty"); err != nil {
		t.Fatalf("RemoveDirAt empty: %v", err)
	}
	if _, err := os.Stat(filepath.Join(tmp, "empty")); !os.IsNotExist(err) {
		t.Error("empty dir should be removed")
	}

	// Non-empty directory must fail.
	if err := RemoveDirAt(d, "nonempty"); err == nil {
		t.Error("expected error removing non-empty directory")
	}
}

func TestLinkAt(t *testing.T) {
	tmp := t.TempDir()
	os.WriteFile(filepath.Join(tmp, "original.txt"), []byte("data"), 0644)
	d := openTestDir(t, tmp)

	if err := LinkAt(d, "original.txt", d, "hardlink.txt", false); err != nil {
		t.Fatalf("LinkAt: %v", err)
	}
	info1, _ := os.Stat(filepath.Join(tmp, "original.txt"))
	info2, _ := os.Stat(filepath.Join(tmp, "hardlink.txt"))
	s1 := info1.Sys().(*syscall.Stat_t)
	s2 := info2.Sys().(*syscall.Stat_t)
	if s1.Ino != s2.Ino {
		t.Error("hard link should share the same inode")
	}
}

func TestReadLinkAt(t *testing.T) {
	tmp := t.TempDir()
	os.Symlink("/absolute/path", filepath.Join(tmp, "abslink"))
	os.Symlink("relative/path", filepath.Join(tmp, "rellink"))
	os.WriteFile(filepath.Join(tmp, "regular"), []byte("x"), 0644)
	d := openTestDir(t, tmp)

	abs, err := ReadLinkAt(d, "abslink")
	if err != nil {
		t.Fatalf("ReadLinkAt abs: %v", err)
	}
	if abs != "/absolute/path" {
		t.Errorf("abs link: got %q, want %q", abs, "/absolute/path")
	}

	rel, err := ReadLinkAt(d, "rellink")
	if err != nil {
		t.Fatalf("ReadLinkAt rel: %v", err)
	}
	if rel != "relative/path" {
		t.Errorf("rel link: got %q, want %q", rel, "relative/path")
	}

	// ReadLinkAt on a regular file must fail.
	if _, err = ReadLinkAt(d, "regular"); err == nil {
		t.Error("expected error for ReadLinkAt on regular file")
	}
}

func TestDupFile(t *testing.T) {
	tmp := t.TempDir()
	f, err := os.CreateTemp(tmp, "dup")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	f.WriteString("original")

	dup, err := DupFile(f)
	if err != nil {
		t.Fatalf("DupFile: %v", err)
	}
	defer dup.Close()

	// Read from the duplicate.
	dup.Seek(0, 0)
	buf := make([]byte, 8)
	n, _ := dup.Read(buf)
	if got := string(buf[:n]); got != "original" {
		t.Errorf("dup read: got %q, want %q", got, "original")
	}

	// Closing the dup should not affect the original.
	dup.Close()
	f.Seek(0, 0)
	buf2 := make([]byte, 8)
	n2, _ := f.Read(buf2)
	if got := string(buf2[:n2]); got != "original" {
		t.Errorf("original after dup close: got %q, want %q", got, "original")
	}
}

// --- RemoveChildren tests (pre-existing, kept for reference) ---

func TestRemoveChildren(t *testing.T) {
	tmpDir := t.TempDir()

	subDir := filepath.Join(tmpDir, "subdir")
	os.Mkdir(subDir, 0755)
	os.WriteFile(filepath.Join(tmpDir, "file1.txt"), []byte("data"), 0644)
	os.WriteFile(filepath.Join(subDir, "file2.txt"), []byte("data"), 0644)

	d, err := os.Open(tmpDir)
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()

	if err := RemoveChildren(d); err != nil {
		t.Errorf("expected no error, got %v", err)
	}
	entries, _ := os.ReadDir(tmpDir)
	if len(entries) != 0 {
		t.Errorf("expected 0 entries after RemoveChildren, got %d", len(entries))
	}
}

func TestRemoveChildren_FirstError(t *testing.T) {
	tmpDir := t.TempDir()
	lockedFile := filepath.Join(tmpDir, "locked")
	os.WriteFile(lockedFile, nil, 0000)

	d, _ := os.Open(tmpDir)
	defer d.Close()

	err := RemoveChildren(d)
	if err != nil {
		if _, ok := err.(*os.PathError); !ok {
			t.Errorf("expected *os.PathError, got %T", err)
		}
	}
}

// --- CopyFolderContents tests ---

// buildDeepTree creates the following 3-level structure under base:
//
// base/
//
//	file1.txt        ("level1")
//	link_to_file1 -> file1.txt
//	subdir1/
//	  file2.txt      ("level2")
//	  subdir2/
//	    file3.txt    ("level3")
//	    link_to_top -> ../../file1.txt
//	    subdir3/
//	      file4.txt  ("deepest")
func buildDeepTree(t *testing.T, base string) {
	t.Helper()
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	must(os.WriteFile(filepath.Join(base, "file1.txt"), []byte("level1"), 0644))
	must(os.Symlink("file1.txt", filepath.Join(base, "link_to_file1")))
	sub1 := filepath.Join(base, "subdir1")
	must(os.Mkdir(sub1, 0755))
	must(os.WriteFile(filepath.Join(sub1, "file2.txt"), []byte("level2"), 0644))
	sub2 := filepath.Join(sub1, "subdir2")
	must(os.Mkdir(sub2, 0755))
	must(os.WriteFile(filepath.Join(sub2, "file3.txt"), []byte("level3"), 0644))
	must(os.Symlink("../../file1.txt", filepath.Join(sub2, "link_to_top")))
	sub3 := filepath.Join(sub2, "subdir3")
	must(os.Mkdir(sub3, 0755))
	must(os.WriteFile(filepath.Join(sub3, "file4.txt"), []byte("deepest"), 0644))
}

func TestCopyFolderContents_NoHardlinks_NoFollowSymlinks(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	buildDeepTree(t, src)

	srcDir := openTestDir(t, src)
	dstDir := openTestDir(t, dst)

	err := CopyFolderContents(context.Background(), srcDir, dstDir, CopyFolderOptions{
		Disallow_hardlinks: true,
		Follow_symlinks:    false,
	})
	if err != nil {
		t.Fatalf("CopyFolderContents: %v", err)
	}

	// All files should be present with correct contents.
	cases := []struct{ path, want string }{
		{"file1.txt", "level1"},
		{"subdir1/file2.txt", "level2"},
		{"subdir1/subdir2/file3.txt", "level3"},
		{"subdir1/subdir2/subdir3/file4.txt", "deepest"},
	}
	for _, c := range cases {
		got := mustReadFile(t, filepath.Join(dst, c.path))
		if got != c.want {
			t.Errorf("%s: got %q, want %q", c.path, got, c.want)
		}
	}

	// Symlinks should be copied verbatim (not resolved).
	symlinks := []struct{ path, want string }{
		{"link_to_file1", "file1.txt"},
		{"subdir1/subdir2/link_to_top", "../../file1.txt"},
	}
	for _, s := range symlinks {
		got, err := os.Readlink(filepath.Join(dst, s.path))
		if err != nil {
			t.Fatalf("readlink %s: %v", s.path, err)
		}
		if got != s.want {
			t.Errorf("symlink %s: got target %q, want %q", s.path, got, s.want)
		}
	}

	// With Disallow_hardlinks, files must have different inodes from source.
	srcInfo, _ := os.Stat(filepath.Join(src, "file1.txt"))
	dstInfo, _ := os.Stat(filepath.Join(dst, "file1.txt"))
	if srcInfo.Sys().(*syscall.Stat_t).Ino == dstInfo.Sys().(*syscall.Stat_t).Ino {
		t.Error("files should not share inodes when Disallow_hardlinks=true")
	}
}

func TestCopyFolderContents_WithHardlinks(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	os.WriteFile(filepath.Join(src, "file.txt"), []byte("data"), 0644)
	os.Mkdir(filepath.Join(src, "sub"), 0755)
	os.WriteFile(filepath.Join(src, "sub", "file2.txt"), []byte("data2"), 0644)

	srcDir := openTestDir(t, src)
	dstDir := openTestDir(t, dst)

	err := CopyFolderContents(context.Background(), srcDir, dstDir, CopyFolderOptions{
		Disallow_hardlinks: false,
		Follow_symlinks:    false,
	})
	if err != nil {
		t.Fatalf("CopyFolderContents: %v", err)
	}

	// Regular files must share inodes (hardlinked).
	for _, name := range []string{"file.txt", "sub/file2.txt"} {
		sInfo, _ := os.Stat(filepath.Join(src, name))
		dInfo, _ := os.Stat(filepath.Join(dst, name))
		sIno := sInfo.Sys().(*syscall.Stat_t).Ino
		dIno := dInfo.Sys().(*syscall.Stat_t).Ino
		if sIno != dIno {
			t.Errorf("%s: expected same inode (hardlink), got src=%d dst=%d", name, sIno, dIno)
		}
	}
}

// TestCopyFolderContents_SymlinkLoop verifies that a symlink creating a
// directory loop (a -> .) is correctly handled: the already-copied directory
// appears as a relative symlink in the destination.
func TestCopyFolderContents_SymlinkLoop(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)

	// src/loop -> . (points back to src itself, creating a loop)
	os.Symlink(".", filepath.Join(src, "loop"))
	os.WriteFile(filepath.Join(src, "file.txt"), []byte("hello"), 0644)

	srcDir := openTestDir(t, src)
	dstDir := openTestDir(t, dst)

	err := CopyFolderContents(context.Background(), srcDir, dstDir, CopyFolderOptions{
		Disallow_hardlinks: true,
		Follow_symlinks:    true,
	})
	if err != nil {
		t.Fatalf("CopyFolderContents with loop: %v", err)
	}

	// file.txt must be present with correct content.
	if got := mustReadFile(t, filepath.Join(dst, "file.txt")); got != "hello" {
		t.Errorf("file.txt: got %q, want %q", got, "hello")
	}

	// loop must exist and be a symlink (not cause infinite recursion).
	linfo, err := os.Lstat(filepath.Join(dst, "loop"))
	if err != nil {
		t.Fatalf("lstat dst/loop: %v", err)
	}
	if linfo.Mode()&os.ModeSymlink == 0 {
		t.Error("dst/loop should be a symlink (loop broken by relative back-reference)")
	}
}

// TestCopyFolderContents_FollowSymlinks_DirectorySymlink tests that when
// Follow_symlinks is true and a symlink points to a subdirectory, the
// directory contents are copied (and the underlying fd is kept alive long
// enough for next_dir to process the queued item — the key bug being tested).
func TestCopyFolderContents_FollowSymlinks_DirectorySymlink(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)

	// src/subdir/ with a file, and src/link_to_subdir -> subdir
	subdir := filepath.Join(src, "subdir")
	os.Mkdir(subdir, 0755)
	os.WriteFile(filepath.Join(subdir, "inner.txt"), []byte("inner"), 0644)
	os.Symlink("subdir", filepath.Join(src, "link_to_subdir"))

	srcDir := openTestDir(t, src)
	dstDir := openTestDir(t, dst)

	err := CopyFolderContents(context.Background(), srcDir, dstDir, CopyFolderOptions{
		Disallow_hardlinks: true,
		Follow_symlinks:    true,
	})
	if err != nil {
		t.Fatalf("CopyFolderContents (follow symlink to dir): %v", err)
	}

	// The real subdir must be copied.
	if got := mustReadFile(t, filepath.Join(dst, "subdir", "inner.txt")); got != "inner" {
		t.Errorf("subdir/inner.txt: got %q, want %q", got, "inner")
	}
}

// TestCopyFolderContents_DeepTree_FollowSymlinks copies the 3-level tree
// with Follow_symlinks=true. Symlinks that cross directory boundaries are
// resolved; symlinks whose targets resolve to the same source file become a
// relative symlink in the destination pointing at the already-copied file.
func TestCopyFolderContents_DeepTree_FollowSymlinks(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	buildDeepTree(t, src)

	srcDir := openTestDir(t, src)
	dstDir := openTestDir(t, dst)

	err := CopyFolderContents(context.Background(), srcDir, dstDir, CopyFolderOptions{
		Disallow_hardlinks: true,
		Follow_symlinks:    true,
	})
	if err != nil {
		t.Fatalf("CopyFolderContents (follow): %v", err)
	}

	// Deep regular files must be present.
	for _, c := range []struct{ path, want string }{
		{"file1.txt", "level1"},
		{"subdir1/file2.txt", "level2"},
		{"subdir1/subdir2/file3.txt", "level3"},
		{"subdir1/subdir2/subdir3/file4.txt", "deepest"},
	} {
		got := mustReadFile(t, filepath.Join(dst, c.path))
		if got != c.want {
			t.Errorf("%s: got %q, want %q", c.path, got, c.want)
		}
	}
}

// TestCopyFolderContents_FilterFiles checks that Filter_files can exclude entries.
func TestCopyFolderContents_FilterFiles(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	os.WriteFile(filepath.Join(src, "keep.txt"), []byte("keep"), 0644)
	os.WriteFile(filepath.Join(src, "skip.txt"), []byte("skip"), 0644)

	srcDir := openTestDir(t, src)
	dstDir := openTestDir(t, dst)

	err := CopyFolderContents(context.Background(), srcDir, dstDir, CopyFolderOptions{
		Disallow_hardlinks: true,
		Filter_files: func(_ *os.File, fi os.FileInfo) bool {
			return fi.Name() != "skip.txt"
		},
	})
	if err != nil {
		t.Fatalf("CopyFolderContents (filter): %v", err)
	}
	if _, err := os.Stat(filepath.Join(dst, "keep.txt")); err != nil {
		t.Error("keep.txt should be present")
	}
	if _, err := os.Stat(filepath.Join(dst, "skip.txt")); !os.IsNotExist(err) {
		t.Error("skip.txt should have been filtered out")
	}
}

// TestCopyFolderContents_CancelledContext verifies that cancellation is
// respected and does not leak file descriptors.
func TestCopyFolderContents_CancelledContext(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("FD leak check requires Linux /proc/self/fd")
	}

	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	buildDeepTree(t, src)

	srcDir := openTestDir(t, src)
	dstDir := openTestDir(t, dst)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // pre-cancel

	before := countOpenFDs()
	_ = CopyFolderContents(ctx, srcDir, dstDir, CopyFolderOptions{
		Disallow_hardlinks: true,
	})
	after := countOpenFDs()

	if after > before {
		t.Errorf("FD leak after cancelled copy: before=%d after=%d", before, after)
	}
}

// TestCopyFolderContents_FDLeaks_Normal verifies that a complete, successful
// copy does not leak file descriptors.
func TestCopyFolderContents_FDLeaks_Normal(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("FD leak check requires Linux /proc/self/fd")
	}

	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)
	buildDeepTree(t, src)

	srcDir := openTestDir(t, src)
	dstDir := openTestDir(t, dst)

	before := countOpenFDs()
	err := CopyFolderContents(context.Background(), srcDir, dstDir, CopyFolderOptions{
		Disallow_hardlinks: true,
		Follow_symlinks:    false,
	})
	after := countOpenFDs()

	if err != nil {
		t.Fatalf("CopyFolderContents: %v", err)
	}
	if after > before {
		t.Errorf("FD leak in normal copy: before=%d after=%d", before, after)
	}
}

// TestCopyFolderContents_FDLeaks_FollowSymlinks_DirSymlink exercises the
// code path that was previously buggy: a symlink pointing to a directory when
// Follow_symlinks=true. Without the fix, the directory fd would be closed
// before next_dir processed the queue item. This test verifies both
// correctness (copy succeeds) and the absence of FD leaks.
func TestCopyFolderContents_FDLeaks_FollowSymlinks_DirSymlink(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("FD leak check requires Linux /proc/self/fd")
	}

	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	dst := filepath.Join(tmp, "dst")
	os.MkdirAll(src, 0755)
	os.MkdirAll(dst, 0755)

	subdir := filepath.Join(src, "subdir")
	os.Mkdir(subdir, 0755)
	os.WriteFile(filepath.Join(subdir, "deep.txt"), []byte("deep"), 0644)
	// Symlink pointing to the subdirectory — the key bug scenario.
	os.Symlink("subdir", filepath.Join(src, "link_to_subdir"))

	srcDir := openTestDir(t, src)
	dstDir := openTestDir(t, dst)

	before := countOpenFDs()
	err := CopyFolderContents(context.Background(), srcDir, dstDir, CopyFolderOptions{
		Disallow_hardlinks: true,
		Follow_symlinks:    true,
	})
	after := countOpenFDs()

	if err != nil {
		t.Fatalf("CopyFolderContents (dir symlink): %v", err)
	}
	if after > before {
		t.Errorf("FD leak with dir symlink: before=%d after=%d", before, after)
	}
	// The real subdir contents must appear in the destination.
	if got := mustReadFile(t, filepath.Join(dst, "subdir", "deep.txt")); got != "deep" {
		t.Errorf("subdir/deep.txt: got %q, want %q", got, "deep")
	}
}
