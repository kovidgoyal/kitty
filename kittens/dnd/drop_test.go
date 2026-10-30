// License: GPLv3 Copyright: 2025, Kovid Goyal, <kovid at kovidgoyal.net>

package dnd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
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
	return runLocalDropAfter(t, dest, uris, action, copy_mode, nil)
}

// Like runLocalDrop but calls before_drop, if not nil, after the kitten has
// opened dest and before the drop is processed.
func runLocalDropAfter(t *testing.T, dest string, uris []parsed_uri, action int, copy_mode string, before_drop func()) (*dnd, error) {
	t.Helper()
	return runLocalDropWithOptions(t, dest, uris, action, &Options{CopyMode: copy_mode}, before_drop)
}

// Like runLocalDrop but with overwrite confirmation enabled. If the drop
// would overwrite existing files, it is left awaiting confirmation.
func runLocalDropConfirming(t *testing.T, dest string, uris []parsed_uri, action int, copy_mode string) (*dnd, error) {
	t.Helper()
	return runLocalDropWithOptions(t, dest, uris, action, &Options{CopyMode: copy_mode, ConfirmDropOverwrite: true}, nil)
}

func runLocalDropWithOptions(t *testing.T, dest string, uris []parsed_uri, action int, opts *Options, before_drop func()) (*dnd, error) {
	t.Helper()
	lp, err := loop.New()
	if err != nil {
		t.Fatal(err)
	}
	d := &dnd{lp: lp, opts: opts, in_test_mode: true}
	if err := d.setup_base_dir(dest); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if d.confirm_drop.staging_dir != nil {
			d.confirm_drop.staging_dir.Close()
		}
		d.reset_drop()
		d.remove_tdir()
		d.drop_output_dir.Close()
	})
	if before_drop != nil {
		before_drop()
	}
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

func TestLocalMoveDestinationAliasesSource(t *testing.T) {
	for _, mode := range []string{"auto", "independent"} {
		for _, confirm := range []bool{false, true} {
			for _, target := range []string{"source", "descendant", "nested", "other-source"} {
				t.Run(fmt.Sprintf("%s/confirm=%t/%s", mode, confirm, target), func(t *testing.T) {
					tmp := t.TempDir()
					src, dst := filepath.Join(tmp, "src"), filepath.Join(tmp, "dst")
					files := map[string]string{"folder/file.txt": "original", "folder/nested/child.txt": "nested", "other/file.txt": "other", "extra.txt": "extra"}
					buildTree(t, src, files, nil)
					buildTree(t, dst, map[string]string{"keep.txt": "keep"}, nil)
					link, linkTarget := "folder", filepath.Join(src, "folder")
					uris := []parsed_uri{{kind: parsed_uri_file, path: filepath.Join(src, "extra.txt")}, {kind: parsed_uri_file, path: filepath.Join(src, "folder")}}
					switch target {
					case "descendant":
						linkTarget = filepath.Join(src, "folder/nested")
					case "nested":
						link, linkTarget = "folder/nested", filepath.Join(src, "folder/nested")
					case "other-source":
						linkTarget = filepath.Join(src, "other")
						uris = append(uris, parsed_uri{kind: parsed_uri_file, path: linkTarget})
					}
					buildTree(t, dst, nil, map[string]string{link: linkTarget})
					run := runLocalDrop
					if confirm {
						run = runLocalDropConfirming
					}
					d, err := run(t, dst, uris, move_on_drop, mode)
					if err == nil && d.confirm_drop.staging_dir != nil {
						err = d.drop_confirm(true)
					}
					if err == nil || !strings.Contains(err.Error(), "directory being moved") {
						t.Errorf("expected a move source overlap error, got %v", err)
					}
					for name, want := range files {
						if got, err := os.ReadFile(filepath.Join(src, name)); err != nil || string(got) != want {
							t.Errorf("source %s: got %q, %v, want %q", name, got, err, want)
						}
					}
					if _, err := os.Lstat(filepath.Join(dst, "extra.txt")); !os.IsNotExist(err) {
						t.Errorf("unrelated file was placed before rejection: %v", err)
					}
					if got, err := os.Readlink(filepath.Join(dst, link)); err != nil || got != linkTarget {
						t.Errorf("destination link: got %q, %v", got, err)
					}
					if got, err := os.ReadFile(filepath.Join(dst, "keep.txt")); err != nil || string(got) != "keep" {
						t.Errorf("existing destination file: got %q, %v", got, err)
					}
				})
			}
		}
	}
}

func TestLocalDropSafeDestinationSymlinks(t *testing.T) {
	for _, mode := range []string{"auto", "independent"} {
		for _, confirm := range []bool{false, true} {
			for _, target := range []string{"copy-to-source", "move-to-unrelated"} {
				t.Run(fmt.Sprintf("%s/confirm=%t/%s", mode, confirm, target), func(t *testing.T) {
					tmp := t.TempDir()
					src, dst, other := filepath.Join(tmp, "src"), filepath.Join(tmp, "dst"), filepath.Join(tmp, "other")
					buildTree(t, src, map[string]string{"folder/file.txt": "original", "folder/nested/child.txt": "nested"}, nil)
					buildTree(t, other, map[string]string{"file.txt": "old", "keep.txt": "keep"}, nil)
					action, linkTarget := copy_on_drop, filepath.Join(src, "folder")
					if target == "move-to-unrelated" {
						action, linkTarget = move_on_drop, other
					}
					buildTree(t, dst, nil, map[string]string{"folder": linkTarget})
					run := runLocalDrop
					if confirm {
						run = runLocalDropConfirming
					}
					d, err := run(t, dst, []parsed_uri{{kind: parsed_uri_file, path: filepath.Join(src, "folder")}}, action, mode)
					if err == nil && confirm {
						if d.confirm_drop.staging_dir == nil {
							t.Fatal("expected overwrite confirmation")
						}
						err = d.drop_confirm(true)
					}
					if err != nil {
						t.Fatal(err)
					}
					for name, want := range map[string]string{"file.txt": "original", "nested/child.txt": "nested"} {
						if got, err := os.ReadFile(filepath.Join(dst, "folder", name)); err != nil || string(got) != want {
							t.Errorf("destination %s: got %q, %v", name, got, err)
						}
					}
					if action == move_on_drop {
						if _, err := os.Lstat(filepath.Join(src, "folder")); !os.IsNotExist(err) {
							t.Errorf("source still present: %v", err)
						}
						if got, err := os.ReadFile(filepath.Join(other, "keep.txt")); err != nil || string(got) != "keep" {
							t.Errorf("existing merge target file: got %q, %v", got, err)
						}
					}
				})
			}
		}
	}
}

func TestLocalMoveDestinationAliasAfterConfirmation(t *testing.T) {
	for _, mode := range []string{"auto", "independent"} {
		t.Run(mode, func(t *testing.T) {
			tmp := t.TempDir()
			src, dst, other := filepath.Join(tmp, "src"), filepath.Join(tmp, "dst"), filepath.Join(tmp, "other")
			buildTree(t, src, map[string]string{"folder/file.txt": "original"}, nil)
			buildTree(t, other, map[string]string{"file.txt": "old"}, nil)
			buildTree(t, dst, nil, map[string]string{"folder": other})
			d, err := runLocalDropConfirming(t, dst, []parsed_uri{{kind: parsed_uri_file, path: filepath.Join(src, "folder")}}, move_on_drop, mode)
			if err != nil {
				t.Fatal(err)
			}
			if len(d.confirm_drop.overwrites) == 0 {
				t.Fatal("expected overwrite confirmation")
			}
			link := filepath.Join(dst, "folder")
			if err := os.Remove(link); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(filepath.Join(src, "folder"), link); err != nil {
				t.Fatal(err)
			}
			if err := d.drop_confirm(true); err == nil || !strings.Contains(err.Error(), "directory being moved") {
				t.Errorf("expected a move source overlap error, got %v", err)
			}
			if got, err := os.ReadFile(filepath.Join(src, "folder/file.txt")); err != nil || string(got) != "original" {
				t.Errorf("source: got %q, %v", got, err)
			}
			if got, err := os.ReadFile(filepath.Join(other, "file.txt")); err != nil || string(got) != "old" {
				t.Errorf("original destination: got %q, %v", got, err)
			}
		})
	}
}

func TestLocalMoveSourceRemovedWhileAwaitingConfirmation(t *testing.T) {
	tmp := t.TempDir()
	src, dst := filepath.Join(tmp, "src"), filepath.Join(tmp, "dst")
	buildTree(t, src, map[string]string{"a/file.txt": "a", "b/file.txt": "b"}, nil)
	buildTree(t, dst, map[string]string{"a/file.txt": "old"}, nil)
	uris := []parsed_uri{{kind: parsed_uri_file, path: filepath.Join(src, "a")}, {kind: parsed_uri_file, path: filepath.Join(src, "b")}}
	d, err := runLocalDropConfirming(t, dst, uris, move_on_drop, "independent")
	if err != nil {
		t.Fatal(err)
	}
	if d.confirm_drop.staging_dir == nil {
		t.Fatal("expected overwrite confirmation")
	}
	if err := os.RemoveAll(filepath.Join(src, "b")); err != nil {
		t.Fatal(err)
	}
	// The staged copy is now the only copy of b, so the drop must still succeed
	if err := d.drop_confirm(true); err != nil {
		t.Fatal(err)
	}
	for name, want := range map[string]string{"a/file.txt": "a", "b/file.txt": "b"} {
		if got, err := os.ReadFile(filepath.Join(dst, name)); err != nil || string(got) != want {
			t.Errorf("destination %s: got %q, %v, want %q", name, got, err, want)
		}
	}
	if _, err := os.Lstat(filepath.Join(src, "a")); !os.IsNotExist(err) {
		t.Errorf("move source still present: %v", err)
	}
}

func TestLocalMoveDirectoryAndFileThroughAlias(t *testing.T) {
	for _, mode := range []string{"auto", "independent"} {
		for _, confirm := range []bool{false, true} {
			for _, selection := range []string{"folder-only", "folder-first", "file-first"} {
				t.Run(fmt.Sprintf("%s/confirm=%t/%s", mode, confirm, selection), func(t *testing.T) {
					tmp := t.TempDir()
					src, dst := filepath.Join(tmp, "src"), filepath.Join(tmp, "dst")
					buildTree(t, src, map[string]string{"folder/file.txt": "directory payload", "file.txt": "top level payload"}, nil)
					buildTree(t, dst, nil, map[string]string{"folder": src})
					uris := []parsed_uri{{kind: parsed_uri_file, path: filepath.Join(src, "folder")}}
					if selection != "folder-only" {
						file := parsed_uri{kind: parsed_uri_file, path: filepath.Join(src, "file.txt")}
						if selection == "file-first" {
							uris = append([]parsed_uri{file}, uris...)
						} else {
							uris = append(uris, file)
						}
					}
					run := runLocalDrop
					if confirm {
						run = runLocalDropConfirming
					}
					d, err := run(t, dst, uris, move_on_drop, mode)
					if err != nil {
						t.Fatal(err)
					}
					if confirm {
						if d.confirm_drop.staging_dir == nil {
							t.Fatal("expected overwrite confirmation")
						}
						if err := d.drop_confirm(true); err != nil {
							t.Fatal(err)
						}
					}
					if got, err := os.ReadFile(filepath.Join(dst, "folder/file.txt")); err != nil || string(got) != "directory payload" {
						t.Errorf("merged directory payload: got %q, %v", got, err)
					}
					if selection != "folder-only" {
						if got, err := os.ReadFile(filepath.Join(dst, "file.txt")); err != nil || string(got) != "top level payload" {
							t.Errorf("top level payload: got %q, %v", got, err)
						}
					}
					if _, err := os.Lstat(filepath.Join(src, "folder")); !os.IsNotExist(err) {
						t.Errorf("move source directory still present: %v", err)
					}
				})
			}
		}
	}
}

func TestLocalMoveSourceReplacedWhileAwaitingConfirmation(t *testing.T) {
	for _, mode := range []string{"auto", "independent"} {
		for _, directory := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/directory=%t", mode, directory), func(t *testing.T) {
				tmp := t.TempDir()
				src, dst := filepath.Join(tmp, "src"), filepath.Join(tmp, "dst")
				name := "item"
				if directory {
					name = "item/file.txt"
				}
				buildTree(t, src, map[string]string{name: "original"}, nil)
				buildTree(t, dst, map[string]string{name: "old destination"}, nil)
				source := filepath.Join(src, "item")
				d, err := runLocalDropConfirming(t, dst, []parsed_uri{{kind: parsed_uri_file, path: source}}, move_on_drop, mode)
				if err != nil {
					t.Fatal(err)
				}
				if d.confirm_drop.staging_dir == nil {
					t.Fatal("expected overwrite confirmation")
				}
				if err := os.Rename(source, source+".original"); err != nil {
					t.Fatal(err)
				}
				buildTree(t, src, map[string]string{name: "replacement"}, nil)
				if err := d.drop_confirm(true); err != nil {
					t.Fatal(err)
				}
				if got, err := os.ReadFile(filepath.Join(src, name)); err != nil || string(got) != "replacement" {
					t.Errorf("replacement source: got %q, %v", got, err)
				}
				if got, err := os.ReadFile(filepath.Join(dst, name)); err != nil || string(got) != "original" {
					t.Errorf("destination: got %q, %v", got, err)
				}
			})
		}
	}
}

func TestMoveSourceReplacementReusingInode(t *testing.T) {
	path := filepath.Join(t.TempDir(), "item")
	if err := os.WriteFile(path, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}
	birth := birth_time(path, info)
	if birth.IsZero() {
		t.Skip("filesystem does not record birth times")
	}
	if got, err := (move_source{info, birth}).current(path); err != nil || got == nil {
		t.Fatalf("unchanged source not recognized: %v, %v", got, err)
	}
	// A replacement with the same inode number differs only in birth time
	if got, err := (move_source{info, birth.Add(-time.Second)}).current(path); err != nil || got != nil {
		t.Fatalf("replacement recognized as the source: %v, %v", got, err)
	}
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

var action_names = map[int]string{copy_on_drop: "copy", move_on_drop: "move"}

func TestLocalDropIntoSourceDirectory(t *testing.T) {
	for _, action := range []int{copy_on_drop, move_on_drop} {
		for _, copy_mode := range []string{"auto", "independent"} {
			for _, location := range []string{"self", "descendant"} {
				for _, alias := range []string{"none", "source-parent", "destination", "case"} {
					t.Run(fmt.Sprintf("%s/%s/%s/%s", action_names[action], copy_mode, location, alias), func(t *testing.T) {
						root := t.TempDir()
						source := filepath.Join(root, "source")
						files := map[string]string{"data.txt": "source data", "child/nested/keep.txt": "destination data"}
						buildTree(t, source, files, nil)
						dest := source
						if location == "descendant" {
							dest = filepath.Join(source, "child", "nested")
						}
						source_path, dest_path := source, dest
						switch alias {
						case "source-parent", "destination":
							path := filepath.Join(t.TempDir(), "alias")
							target := root
							if alias == "destination" {
								target = dest
							}
							if err := os.Symlink(target, path); err != nil {
								t.Fatal(err)
							}
							if alias == "source-parent" {
								source_path = filepath.Join(path, "source")
							} else {
								dest_path = path
							}
						case "case":
							source_path = filepath.Join(root, "SOURCE")
							if _, err := os.Stat(source_path); os.IsNotExist(err) {
								t.Skip("case-sensitive filesystem")
							} else if err != nil {
								t.Fatal(err)
							}
						}
						incoming := filepath.Join(root, "incoming.txt")
						if err := os.WriteFile(incoming, []byte("incoming data"), 0644); err != nil {
							t.Fatal(err)
						}
						uris := []parsed_uri{
							{kind: parsed_uri_file, path: incoming},
							{kind: parsed_uri_data, mime: "text/plain", data: []byte("data URI")},
							{kind: parsed_uri_file, path: source_path},
						}
						d, err := runLocalDrop(t, dest_path, uris, action, copy_mode)
						if err == nil {
							t.Fatal("dropping a directory into itself must fail")
						}
						if d.tdir_counter != 0 || d.drop_status.dropping_to != nil {
							t.Errorf("invalid drop started staging before failing: %v", err)
						}
						for path, want := range files {
							if data, err := os.ReadFile(filepath.Join(source, path)); err != nil || string(data) != want {
								t.Errorf("source %s changed: %q, %v", path, data, err)
							}
						}
						if data, err := os.ReadFile(incoming); err != nil || string(data) != "incoming data" {
							t.Errorf("incoming file changed: %q, %v", data, err)
						}
					})
				}
			}
		}
	}
}

func TestLocalDropOutsideSourceDirectory(t *testing.T) {
	for _, action := range []int{copy_on_drop, move_on_drop} {
		for _, copy_mode := range []string{"auto", "independent"} {
			for _, location := range []string{"sibling", "symlink", "search-only-parent"} {
				t.Run(fmt.Sprintf("%s/%s/%s", action_names[action], copy_mode, location), func(t *testing.T) {
					root := t.TempDir()
					source := filepath.Join(root, "source")
					buildTree(t, source, map[string]string{"data.txt": "source data", "child/keep.txt": "destination data"}, nil)
					path, dest := source, filepath.Join(root, "source-sibling")
					if location == "symlink" {
						path, dest = filepath.Join(root, "link"), filepath.Join(source, "child")
						if err := os.Symlink(source, path); err != nil {
							t.Fatal(err)
						}
					} else {
						if location == "search-only-parent" {
							dest = filepath.Join(root, "search-only", "dest")
						}
						if err := os.MkdirAll(dest, 0755); err != nil {
							t.Fatal(err)
						}
						if location == "search-only-parent" {
							parent := filepath.Dir(dest)
							t.Cleanup(func() {
								if err := os.Chmod(parent, 0755); err != nil {
									t.Error(err)
								}
							})
							if err := os.Chmod(parent, 0111); err != nil {
								t.Fatal(err)
							}
						}
					}
					d, err := runLocalDrop(t, dest, []parsed_uri{{kind: parsed_uri_file, path: path}}, action, copy_mode)
					if err != nil {
						t.Fatal(err)
					}
					if d.num_dropped_files != 1 {
						t.Errorf("got %d dropped files, want 1", d.num_dropped_files)
					}
					if location == "symlink" {
						if target, err := os.Readlink(filepath.Join(dest, "link")); err != nil || target != source {
							t.Errorf("copied symlink: %q, %v", target, err)
						}
					} else if data, err := os.ReadFile(filepath.Join(dest, "source", "data.txt")); err != nil || string(data) != "source data" {
						t.Errorf("copied data: %q, %v", data, err)
					}
					if action == move_on_drop {
						if _, err := os.Lstat(path); !os.IsNotExist(err) {
							t.Errorf("moved source still exists: %v", err)
						}
					}
				})
			}
		}
	}
}

func TestLocalDropIntoMovedDestination(t *testing.T) {
	for _, action := range []int{copy_on_drop, move_on_drop} {
		for _, location := range []string{"outside", "inside"} {
			t.Run(action_names[action]+"/"+location, func(t *testing.T) {
				root := t.TempDir()
				source := filepath.Join(root, "source")
				buildTree(t, source, map[string]string{"data.txt": "source data", "child/keep.txt": "keep"}, nil)
				dest, moved_to := filepath.Join(root, "dest"), filepath.Join(root, "moved")
				if location == "inside" {
					dest, moved_to = filepath.Join(root, "dest"), filepath.Join(source, "child", "moved")
				}
				if err := os.Mkdir(dest, 0755); err != nil {
					t.Fatal(err)
				}
				// Replace the original path so that a path based check would
				// look at the wrong directory.
				d, err := runLocalDropAfter(t, dest, []parsed_uri{{kind: parsed_uri_file, path: source}}, action, "auto", func() {
					if err := os.Rename(dest, moved_to); err != nil {
						t.Fatal(err)
					}
					if err := os.Mkdir(dest, 0755); err != nil {
						t.Fatal(err)
					}
				})
				if location == "inside" {
					if err == nil {
						t.Fatal("dropping a directory into a destination moved inside it must fail")
					}
					if d.tdir_counter != 0 {
						t.Errorf("invalid drop started staging before failing: %v", err)
					}
					if data, err := os.ReadFile(filepath.Join(source, "data.txt")); err != nil || string(data) != "source data" {
						t.Errorf("source changed: %q, %v", data, err)
					}
					return
				}
				if err != nil {
					t.Fatal(err)
				}
				if data, err := os.ReadFile(filepath.Join(moved_to, "source", "data.txt")); err != nil || string(data) != "source data" {
					t.Errorf("copied data: %q, %v", data, err)
				}
			})
		}
	}
}

func TestLocalCopySkipsStagingDirectory(t *testing.T) {
	// Simulate a route to the staging directory that the up-front check
	// cannot detect, such as a bind mount, by bypassing that check.
	for _, action := range []int{copy_on_drop, move_on_drop} {
		t.Run(action_names[action], func(t *testing.T) {
			source := filepath.Join(t.TempDir(), "source")
			buildTree(t, source, map[string]string{"data.txt": "source data"}, nil)
			staging_path := filepath.Join(source, "staging")
			if err := os.Mkdir(staging_path, 0700); err != nil {
				t.Fatal(err)
			}
			staging, err := os.Open(staging_path)
			if err != nil {
				t.Fatal(err)
			}
			defer staging.Close()
			if err := do_local_copy(context.Background(), staging, []string{source}, action, "auto"); err != nil {
				t.Fatal(err)
			}
			if data, err := os.ReadFile(filepath.Join(staging_path, "source", "data.txt")); err != nil || string(data) != "source data" {
				t.Errorf("copied data: %q, %v", data, err)
			}
			if _, err := os.Lstat(filepath.Join(staging_path, "source", "staging")); !os.IsNotExist(err) {
				t.Errorf("staging directory was copied into itself: %v", err)
			}
		})
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

	got, err := find_overwrites(srcDir, dstDir, nil)
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

	got, err := find_overwrites(srcDir, dstDir, nil)
	if err != nil {
		t.Fatalf("find_overwrites: %v", err)
	}
	if len(got) != 1 || got[0] != "shared.txt" {
		t.Errorf("expected [shared.txt], got %v", got)
	}
}

func TestFindOverwritesFilesystemAliases(t *testing.T) {
	for _, tc := range []struct{ name, src, dest string }{
		{"case", "report.txt", "Report.txt"},
		{"unicode", "cafe\u0301.txt", "caf\u00e9.txt"},
		{"directory", "folder/file.txt", "Folder/file.txt"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			src, dest := t.TempDir(), t.TempDir()
			buildTree(t, src, map[string]string{tc.src: "incoming"}, nil)
			buildTree(t, dest, map[string]string{tc.dest: "original"}, nil)
			alias, err := os.Stat(filepath.Join(dest, tc.src))
			if os.IsNotExist(err) {
				t.Skip("destination filesystem does not alias these names")
			} else if err != nil {
				t.Fatal(err)
			}
			original, err := os.Stat(filepath.Join(dest, tc.dest))
			if err != nil {
				t.Fatal(err)
			}
			if !os.SameFile(alias, original) {
				t.Fatal("names do not refer to the same destination file")
			}
			got, err := find_overwrites(openDir(t, src), openDir(t, dest), nil)
			if err != nil {
				t.Fatal(err)
			}
			// The existing entry is reported under the name it is stored as,
			// which some filesystems normalize.
			entries, err := os.ReadDir(dest)
			if err != nil || len(entries) != 1 {
				t.Fatalf("unexpected destination contents: %v %v", entries, err)
			}
			_, rest, _ := strings.Cut(tc.dest, "/")
			want := filepath.Join(entries[0].Name(), rest)
			if len(got) != 1 || got[0] != want {
				t.Errorf("got overwrites %q, want [%q]", got, want)
			}
		})
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

	got, err := find_overwrites(srcDir, dstDir, nil)
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

	got, err := find_overwrites(srcDir, dstDir, nil)
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

	got, err := find_overwrites(srcDir, dstDir, nil)
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

	got, err := find_overwrites(srcDir, dstDir, nil)
	if err != nil {
		t.Fatalf("find_overwrites: %v", err)
	}
	// A directory in src vs a file in dst should be reported.
	if len(got) != 1 || got[0] != "conflict" {
		t.Errorf("expected [conflict], got %v", got)
	}
}

// TestFindOverwrites_FileVsDir verifies that a dropped file that would
// replace an existing directory is an error up front, as rename_contents
// cannot replace a directory with a file.
func TestFindOverwrites_FileVsDir(t *testing.T) {
	src, dst := t.TempDir(), t.TempDir()
	buildTree(t, src, map[string]string{"conflict": "file"}, nil)
	buildTree(t, dst, map[string]string{"conflict/x.txt": "x"}, nil)
	if got, err := find_overwrites(openDir(t, src), openDir(t, dst), nil); err == nil {
		t.Fatalf("expected an error, got overwrites %v", got)
	}
}

// TestSymlinkToDirInDestIsMerged verifies that a symlink to a directory in
// the destination is merged into by rename_contents and that find_overwrites
// reports the files in the symlink target that will be overwritten.
func TestSymlinkToDirInDestIsMerged(t *testing.T) {
	tmp := t.TempDir()
	src, dst, target := filepath.Join(tmp, "src"), filepath.Join(tmp, "dst"), filepath.Join(tmp, "target")
	buildTree(t, src, map[string]string{"folder/file.txt": "new", "folder/new.txt": "new"}, nil)
	buildTree(t, target, map[string]string{"file.txt": "old", "other.txt": "old"}, nil)
	buildTree(t, dst, nil, map[string]string{"folder": target})
	srcDir, dstDir := openDir(t, src), openDir(t, dst)

	got, err := find_overwrites(srcDir, dstDir, nil)
	if err != nil {
		t.Fatalf("find_overwrites: %v", err)
	}
	if want := []string{filepath.Join("folder", "file.txt")}; !equalStringSlices(got, want) {
		t.Errorf("find_overwrites: got %v, want %v", got, want)
	}
	if err := rename_contents(srcDir, dstDir); err != nil {
		t.Fatalf("rename_contents: %v", err)
	}
	if st, err := os.Lstat(filepath.Join(dst, "folder")); err != nil || st.Mode()&os.ModeSymlink == 0 {
		t.Errorf("dst/folder is no longer a symlink: %v %v", st, err)
	}
	for name, want := range map[string]string{"file.txt": "new", "new.txt": "new", "other.txt": "old"} {
		if data, err := os.ReadFile(filepath.Join(target, name)); err != nil || string(data) != want {
			t.Errorf("target/%s: got %q %v, want %q", name, data, err, want)
		}
	}
}

// --- rename_contents tests ---

// TestRenameContents_DirReplacesNonDir verifies that a dropped directory
// replaces an existing file or dangling symlink of the same name.
func TestRenameContents_DirReplacesNonDir(t *testing.T) {
	for _, tc := range []struct {
		name            string
		files, symlinks map[string]string
	}{
		{"file", map[string]string{"conflict": "file"}, nil},
		{"dangling symlink", nil, map[string]string{"conflict": "nonexistent"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			src, dst := t.TempDir(), t.TempDir()
			buildTree(t, src, map[string]string{"conflict/a.txt": "a"}, nil)
			buildTree(t, dst, tc.files, tc.symlinks)
			if err := rename_contents(openDir(t, src), openDir(t, dst)); err != nil {
				t.Fatalf("rename_contents: %v", err)
			}
			if data, err := os.ReadFile(filepath.Join(dst, "conflict", "a.txt")); err != nil || string(data) != "a" {
				t.Errorf("dst/conflict/a.txt: got %q %v", data, err)
			}
		})
	}
}

// TestRenameContents_FileVsDir verifies that replacing an existing directory
// with a file fails and leaves the directory intact.
func TestRenameContents_FileVsDir(t *testing.T) {
	src, dst := t.TempDir(), t.TempDir()
	buildTree(t, src, map[string]string{"conflict": "file"}, nil)
	buildTree(t, dst, map[string]string{"conflict/x.txt": "x"}, nil)
	if err := rename_contents(openDir(t, src), openDir(t, dst)); err == nil {
		t.Fatal("expected an error")
	}
	if _, err := os.Stat(filepath.Join(dst, "conflict", "x.txt")); err != nil {
		t.Errorf("dst/conflict/x.txt missing: %v", err)
	}
}

func TestUniqifyChildNamesNormalization(t *testing.T) {
	got := uniqify_child_names([]string{"caf\u00e9.txt", "Cafe\u0301.txt", "other"}, false)
	want := []string{"caf\u00e9.txt", fmt.Sprintf(case_conflict_template, 1, "Cafe\u0301.txt"), "other"}
	if !equalStringSlices(got, want) {
		t.Errorf("got %q, want %q", got, want)
	}
}

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

// TestSetupBaseDirDetectsNameAliases verifies that setup_base_dir detects
// whether the filesystem treats names differing in case or Unicode
// normalization as aliases and leaves no probe files behind.
func TestSetupBaseDirDetectsNameAliases(t *testing.T) {
	dest := t.TempDir()
	buildTree(t, dest, map[string]string{"Probe": "", "é": ""}, nil)
	_, cerr := os.Lstat(filepath.Join(dest, "probe"))
	_, nerr := os.Lstat(filepath.Join(dest, "é"))
	want := os.IsNotExist(cerr) && os.IsNotExist(nerr)
	for _, name := range []string{"Probe", "é"} {
		if err := os.Remove(filepath.Join(dest, name)); err != nil {
			t.Fatal(err)
		}
	}
	d, err := runLocalDrop(t, dest, nil, copy_on_drop, "")
	if err != nil {
		t.Fatal(err)
	}
	if d.is_case_sensitive_filesystem != want {
		t.Errorf("is_case_sensitive_filesystem: got %v, want %v", d.is_case_sensitive_filesystem, want)
	}
	entries, err := os.ReadDir(d.base_tempdir.Name())
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Errorf("probe files left in the base temporary directory: %v", entries)
	}
}
