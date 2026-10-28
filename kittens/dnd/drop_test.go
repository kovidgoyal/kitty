// License: GPLv3 Copyright: 2025, Kovid Goyal, <kovid at kovidgoyal.net>

package dnd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"testing"
	"time"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
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
// content. Each entry creates a regular file with the given content (parent
// directories are created automatically). Symlink entries are expressed via
// the separate symlinks map: relative link name -> target string.
func buildTree(t *testing.T, base string, files map[string]string, symlinks map[string]string) {
	t.Helper()
	for rel, content := range files {
		full := filepath.Join(base, rel)
		if err := os.MkdirAll(filepath.Dir(full), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, []byte(content), 0644); err != nil {
			t.Fatal(err)
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

func TestLocalCopyHardlinkPolicy(t *testing.T) {
	for _, tc := range []struct {
		name          string
		action        int
		copy_mode     string
		want_hardlink bool
	}{
		{"copy-auto", copy_on_drop, "auto", true},
		{"copy-independent", copy_on_drop, "independent", false},
		{"move-auto", move_on_drop, "auto", true},
		{"move-independent", move_on_drop, "independent", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			tmp := t.TempDir()
			src := filepath.Join(tmp, "src")
			dst := filepath.Join(tmp, "dst")
			files := map[string]string{"file.txt": "top level", "folder/nested.txt": "nested"}
			if err := os.Mkdir(dst, 0755); err != nil {
				t.Fatal(err)
			}
			buildTree(t, src, files, nil)

			if err := do_local_copy(context.Background(), openDir(t, dst), []string{filepath.Join(src, "file.txt"), filepath.Join(src, "folder")}, tc.action, tc.copy_mode); err != nil {
				t.Fatalf("do_local_copy: %v", err)
			}
			for path, content := range files {
				source_info, err := os.Stat(filepath.Join(src, path))
				if err != nil {
					t.Fatal(err)
				}
				copied := filepath.Join(dst, path)
				copied_info, err := os.Stat(copied)
				if err != nil {
					t.Fatal(err)
				}
				if same := os.SameFile(source_info, copied_info); same != tc.want_hardlink {
					t.Errorf("os.SameFile() for %s: got %v, want %v", path, same, tc.want_hardlink)
				}
				if data, err := os.ReadFile(copied); err != nil {
					t.Fatal(err)
				} else if string(data) != content {
					t.Errorf("copied file %s has unexpected content", path)
				}
			}
		})
	}
}

func runLocalDrop(t *testing.T, dest string, uris []parsed_uri, action int, copy_mode string) (*dnd, error) {
	t.Helper()
	lp, err := loop.New()
	if err != nil {
		t.Fatal(err)
	}
	d := &dnd{lp: lp, opts: &Options{CopyMode: copy_mode}, in_test_mode: true}
	if err := d.setup_base_dir(dest); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		d.reset_drop()
		d.remove_tdir()
		d.drop_output_dir.Close()
	})
	d.drop_status = drop_status{action: action, reading_data: true, uri_list: uris}
	if err := d.all_mime_data_dropped(); err != nil {
		return d, err
	}
	deadline := time.Now().Add(5 * time.Second)
	for d.drop_status.local_copy.ctx != nil {
		if time.Now().After(deadline) {
			t.Fatal("local drop did not complete")
		}
		if err := d.drop_on_wakeup(); err != nil {
			return d, err
		}
		time.Sleep(time.Millisecond)
	}
	return d, nil
}

func TestLocalMoveToSourceDirectory(t *testing.T) {
	for _, copy_mode := range []string{"auto", "independent"} {
		for _, alias := range []string{"none", "source", "destination"} {
			for _, name := range []string{"file.txt", "folder", "link", "dangling"} {
				t.Run(copy_mode+"/"+alias+"/"+name, func(t *testing.T) {
					dest := t.TempDir()
					files := map[string]string{"file.txt": "original contents", "folder/nested/file.txt": "nested contents"}
					links := map[string]string{"link": "file.txt", "dangling": "missing"}
					buildTree(t, dest, files, links)
					before, err := os.Lstat(filepath.Join(dest, name))
					if err != nil {
						t.Fatal(err)
					}
					source_dir, dest_dir := dest, dest
					if alias != "none" {
						path := filepath.Join(t.TempDir(), "alias")
						if err := os.Symlink(dest, path); err != nil {
							t.Fatal(err)
						}
						if alias == "source" {
							source_dir = path
						} else {
							dest_dir = path
						}
					}
					d, err := runLocalDrop(t, dest_dir, []parsed_uri{{kind: parsed_uri_file, path: filepath.Join(source_dir, name)}}, move_on_drop, copy_mode)
					if err != nil {
						t.Fatal(err)
					}
					for path, want := range files {
						data, err := os.ReadFile(filepath.Join(dest, path))
						if err != nil {
							t.Errorf("source %s disappeared after moving to its own directory: %v", path, err)
						} else if string(data) != want {
							t.Errorf("source %s: got %q, want %q", path, data, want)
						}
					}
					for path, want := range links {
						if got, err := os.Readlink(filepath.Join(dest, path)); err != nil || got != want {
							t.Errorf("symlink %s: got %q, %v, want %q", path, got, err, want)
						}
					}
					if after, err := os.Lstat(filepath.Join(dest, name)); err != nil || !os.SameFile(before, after) {
						t.Errorf("moving %s into its own directory changed its identity: %v", name, err)
					}
					if d.num_dropped_files != 0 {
						t.Errorf("counted %d dropped files for a no-op move", d.num_dropped_files)
					}
				})
			}
		}
	}
}

func TestLocalDropMixedSourceDirectories(t *testing.T) {
	for _, tc := range []struct {
		name      string
		action    int
		copy_mode string
	}{
		{"copy-auto", copy_on_drop, "auto"},
		{"copy-independent", copy_on_drop, "independent"},
		{"move-auto", move_on_drop, "auto"},
		{"move-independent", move_on_drop, "independent"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			src, dest := t.TempDir(), t.TempDir()
			local := map[string]string{"keep.txt": "keep file", "folder/keep.txt": "keep directory"}
			incoming := map[string]string{"moved.txt": "incoming file", "incoming/nested.txt": "incoming directory", "linked.txt": "hardlinked file"}
			buildTree(t, dest, local, nil)
			buildTree(t, src, incoming, nil)
			if err := os.Link(filepath.Join(src, "linked.txt"), filepath.Join(dest, "linked.txt")); err != nil {
				t.Fatal(err)
			}
			uris := []parsed_uri{
				{kind: parsed_uri_file, path: filepath.Join(dest, "keep.txt")},
				{kind: parsed_uri_file, path: filepath.Join(dest, "folder")},
				{kind: parsed_uri_file},
				{kind: parsed_uri_data, mime: "text/plain", data: []byte("data URI contents")},
			}
			for _, name := range []string{"moved.txt", "incoming", "linked.txt"} {
				uris = append(uris, parsed_uri{kind: parsed_uri_file, path: filepath.Join(src, name)})
			}
			d, err := runLocalDrop(t, dest, uris, tc.action, tc.copy_mode)
			if err != nil {
				t.Fatal(err)
			}
			for _, files := range []map[string]string{local, incoming, {"data-uri-1.txt": "data URI contents"}} {
				for path, want := range files {
					if data, err := os.ReadFile(filepath.Join(dest, path)); err != nil || string(data) != want {
						t.Errorf("dropped file %s: got %q, %v, want %q", path, data, err, want)
					}
				}
			}
			for path, want := range incoming {
				data, err := os.ReadFile(filepath.Join(src, path))
				if tc.action == move_on_drop {
					if !os.IsNotExist(err) {
						t.Errorf("source %s still exists after moving: %v", path, err)
					}
				} else if err != nil || string(data) != want {
					t.Errorf("copy changed source %s: got %q, %v, want %q", path, data, err, want)
				}
			}
			want_count := 6
			if tc.action == move_on_drop {
				want_count = 4
			}
			if d.num_dropped_files != want_count {
				t.Errorf("got %d dropped files, want %d", d.num_dropped_files, want_count)
			}
		})
	}
}

func TestLocalMoveMissingSource(t *testing.T) {
	dest := t.TempDir()
	uris := []parsed_uri{{kind: parsed_uri_file, path: filepath.Join(dest, "missing")}}
	if _, err := runLocalDrop(t, dest, uris, move_on_drop, "auto"); !os.IsNotExist(err) {
		t.Fatalf("got %v, want a missing source error", err)
	}
}

func TestLocalCopyDuplicateBasenames(t *testing.T) {
	for _, tc := range []struct {
		name      string
		action    int
		copy_mode string
	}{
		{"copy-auto", copy_on_drop, "auto"},
		{"copy-independent", copy_on_drop, "independent"},
		{"move-auto", move_on_drop, "auto"},
		{"move-independent", move_on_drop, "independent"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for _, kind := range []string{"files", "directories", "repeated-source", "case-conflict", "existing-name"} {
				t.Run(kind, func(t *testing.T) {
					tmp := t.TempDir()
					src := filepath.Join(tmp, "src")
					dst := filepath.Join(tmp, "dst")
					first, second := "first/file.txt", "second/file.txt"
					switch kind {
					case "directories":
						first, second = "first/folder/file.txt", "second/folder/file.txt"
					case "case-conflict":
						second = "second/FILE.txt"
					}
					files := map[string]string{first: "FIRST original", second: "SECOND original"}
					buildTree(t, src, files, nil)
					if err := os.Mkdir(dst, 0755); err != nil {
						t.Fatal(err)
					}
					paths := []string{filepath.Join(src, first), filepath.Join(src, second)}
					want := []string{"FIRST original", "SECOND original"}
					switch kind {
					case "directories":
						paths[0], paths[1] = filepath.Dir(paths[0]), filepath.Dir(paths[1])
					case "repeated-source":
						paths[1], want[1] = paths[0], want[0]
					case "existing-name":
						buildTree(t, dst, map[string]string{"file.txt": "existing", fmt.Sprintf(case_conflict_template, 1, "file.txt"): "existing conflict"}, nil)
						want = append(want, "existing", "existing conflict")
					}
					if err := do_local_copy(context.Background(), openDir(t, dst), paths, tc.action, tc.copy_mode); err != nil {
						t.Fatal(err)
					}
					for path, want := range files {
						data, err := os.ReadFile(filepath.Join(src, path))
						if err != nil {
							t.Fatal(err)
						}
						if string(data) != want {
							t.Errorf("source %s: got %q, want %q", path, data, want)
						}
					}
					entries, err := os.ReadDir(dst)
					if err != nil {
						t.Fatal(err)
					}
					var contents []string
					for _, entry := range entries {
						path := filepath.Join(dst, entry.Name())
						if kind == "directories" {
							path = filepath.Join(path, "file.txt")
						}
						data, err := os.ReadFile(path)
						if err != nil {
							t.Fatal(err)
						}
						contents = append(contents, string(data))
					}
					if got, want := sortedStrings(contents), sortedStrings(want); !equalStringSlices(got, want) {
						t.Errorf("dropped file contents: got %q, want %q", got, want)
					}
				})
			}
		})
	}
}

func TestLocalCopySymlinkNameConflict(t *testing.T) {
	for _, tc := range []struct {
		name                         string
		target_exists, symlink_first bool
	}{
		{"symlink-first", true, true},
		{"file-first", true, false},
		{"dangling-symlink-first", false, true},
		{"dangling-file-first", false, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			tmp := t.TempDir()
			src, dst := filepath.Join(tmp, "src"), filepath.Join(tmp, "dst")
			target := filepath.Join(src, "target.txt")
			files := map[string]string{"file/file.txt": "FILE original"}
			if tc.target_exists {
				files["target.txt"] = "TARGET original"
			}
			buildTree(t, src, files, map[string]string{"link/file.txt": target})
			if err := os.Mkdir(dst, 0755); err != nil {
				t.Fatal(err)
			}
			paths := []string{filepath.Join(src, "file/file.txt"), filepath.Join(src, "link/file.txt")}
			if tc.symlink_first {
				paths[0], paths[1] = paths[1], paths[0]
			}
			if err := do_local_copy(context.Background(), openDir(t, dst), paths, copy_on_drop, "auto"); err != nil {
				t.Fatal(err)
			}
			for path, want := range files {
				if data, err := os.ReadFile(filepath.Join(src, path)); err != nil {
					t.Fatal(err)
				} else if string(data) != want {
					t.Errorf("source %s: got %q, want %q", path, data, want)
				}
			}
			if !tc.target_exists {
				if _, err := os.Lstat(target); !os.IsNotExist(err) {
					t.Errorf("dangling symlink target was created: %v", err)
				}
			}
			entries, err := os.ReadDir(dst)
			if err != nil {
				t.Fatal(err)
			}
			if len(entries) != 2 {
				t.Fatalf("got %d dropped entries, want 2", len(entries))
			}
			num_symlinks := 0
			for _, entry := range entries {
				path := filepath.Join(dst, entry.Name())
				if entry.Type()&os.ModeSymlink != 0 {
					num_symlinks++
					if got, err := os.Readlink(path); err != nil || got != target {
						t.Errorf("dropped symlink: got %q, %v, want %q", got, err, target)
					}
				} else if data, err := os.ReadFile(path); err != nil || string(data) != "FILE original" {
					t.Errorf("dropped file: got %q, %v, want FILE original", data, err)
				}
			}
			if num_symlinks != 1 {
				t.Errorf("got %d dropped symlinks, want 1", num_symlinks)
			}
		})
	}
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
