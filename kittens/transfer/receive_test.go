// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"bytes"
	"compress/zlib"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

var _ = fmt.Print

func TestReceiveEmptyFile(t *testing.T) {
	tdir := t.TempDir()

	zlib_compress := func(data []byte) []byte {
		var b bytes.Buffer
		w := zlib.NewWriter(&b)
		if _, err := w.Write(data); err != nil {
			t.Fatal(err)
		}
		if err := w.Close(); err != nil {
			t.Fatal(err)
		}
		return b.Bytes()
	}

	receive := func(name, compress string, size int64, expected_compression Compression, chunks ...[]byte) string {
		t.Helper()
		ftc := &FileTransmissionCommand{Action: Action_file, File_id: "0", Name: name, Ftype: FileType_regular, Size: size}
		f, err := new_remote_file(&Options{Compress: compress}, ftc, 1)
		if err != nil {
			t.Fatal(err)
		}
		if f.compression_type != expected_compression {
			t.Fatalf("Unexpected compression type for %s: %s != %s", name, f.compression_type, expected_compression)
		}
		f.expanded_local_path = filepath.Join(tdir, name)
		for i, chunk := range chunks {
			is_last := i == len(chunks)-1
			if _, err = f.write_data(chunk, is_last); err != nil {
				t.Fatalf("Writing chunk %d of %s failed with error: %s", i, name, err)
			}
		}
		if f.actual_file != nil {
			t.Fatalf("Output file for %s not closed after last chunk", name)
		}
		return f.expanded_local_path
	}

	assert_contents := func(path string, expected []byte) {
		t.Helper()
		actual, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("Failed to read %s with error: %s", path, err)
		}
		if !bytes.Equal(actual, expected) {
			t.Fatalf("Contents of %s incorrect: %q != %q", path, actual, expected)
		}
	}

	// A single end_data with no payload, as sent for empty files
	assert_contents(receive("empty", "never", 0, Compression_none, nil), nil)
	// Parent directories must be created for empty files too
	assert_contents(receive(filepath.Join("sub", "dir", "empty"), "never", 0, Compression_none, nil), nil)

	// An existing file must be truncated when the source is empty
	existing := filepath.Join(tdir, "existing")
	if err := os.WriteFile(existing, []byte("stale contents"), 0o600); err != nil {
		t.Fatal(err)
	}
	assert_contents(receive("existing", "never", 0, Compression_none, nil), nil)

	// A zlib stream that decompresses to nothing, which happens when the
	// file shrinks to empty after its metadata was sent
	assert_contents(receive("zempty", "always", 8192, Compression_zlib, zlib_compress(nil)), nil)
	zstream := zlib_compress(nil)
	assert_contents(receive("zempty-split", "always", 8192, Compression_zlib, zstream[:1], zstream[1:]), nil)

	// Non-empty files continue to work, including when the last chunk is empty
	assert_contents(receive("nonempty", "never", 3, Compression_none, []byte("abc"), nil), []byte("abc"))
	assert_contents(receive("znonempty", "always", 8192, Compression_zlib, zlib_compress([]byte("abc"))), []byte("abc"))
}

func TestReceiveEmptyFileError(t *testing.T) {
	tdir := t.TempDir()
	// Make the destination impossible to create by having its parent be a regular file
	blocker := filepath.Join(tdir, "blocker")
	if err := os.WriteFile(blocker, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	ftc := &FileTransmissionCommand{Action: Action_file, File_id: "0", Name: "empty", Ftype: FileType_regular}
	f, err := new_remote_file(&Options{Compress: "never"}, ftc, 1)
	if err != nil {
		t.Fatal(err)
	}
	f.expanded_local_path = filepath.Join(blocker, "empty")
	_, err = f.write_data(nil, true)
	if err == nil {
		t.Fatalf("Receiving an empty file into an uncreatable path did not fail")
	}
	if !strings.Contains(err.Error(), f.expanded_local_path) {
		t.Fatalf("Error does not mention the destination path: %s", err)
	}
}

func TestReceiveReplacesExistingLinks(t *testing.T) {
	for _, link := range []struct {
		name          string
		create        func(string, string) error
		target_exists bool
	}{
		{"symlink", os.Symlink, true},
		{"hardlink", os.Link, true},
		{"dangling_symlink", os.Symlink, false},
	} {
		for _, data := range []string{"", "incoming contents"} {
			t.Run(fmt.Sprintf("%s/size=%d", link.name, len(data)), func(t *testing.T) {
				dir := t.TempDir()
				target := filepath.Join(dir, "unrelated")
				const original = "keep these contents"
				if link.target_exists {
					if err := os.WriteFile(target, []byte(original), 0o600); err != nil {
						t.Fatal(err)
					}
				}
				dest := filepath.Join(dir, "downloads", "received")
				if err := os.Mkdir(filepath.Dir(dest), 0o755); err != nil {
					t.Fatal(err)
				}
				if err := link.create(target, dest); err != nil {
					t.Fatal(err)
				}
				f, err := new_remote_file(&Options{Compress: "never"}, &FileTransmissionCommand{
					File_id: "0", Ftype: FileType_regular, Size: int64(len(data)), Permissions: 0o644,
				}, 1)
				if err != nil {
					t.Fatal(err)
				}
				f.expanded_local_path = dest
				t.Cleanup(func() { _ = f.close() })
				if _, err := f.write_data([]byte(data), true); err != nil {
					t.Fatal(err)
				}
				m := manager{files: []*remote_file{f}}
				if err := m.finalize_transfer(); err != nil {
					t.Fatal(err)
				}
				st, err := os.Lstat(dest)
				if err != nil || !st.Mode().IsRegular() {
					t.Fatalf("Destination is not a regular file: %v, %v", st, err)
				}
				if actual, err := os.ReadFile(dest); err != nil || string(actual) != data {
					t.Fatalf("Incorrect received contents: %q, %v", actual, err)
				}
				if !link.target_exists {
					if _, err := os.Lstat(target); !os.IsNotExist(err) {
						t.Fatalf("Dangling symlink target was created: %v", err)
					}
				} else {
					if actual, err := os.ReadFile(target); err != nil || string(actual) != original {
						t.Fatalf("Unrelated file was modified: %q, %v", actual, err)
					}
					if st, err := os.Stat(target); err != nil || st.Mode().Perm() != 0o600 {
						t.Fatalf("Unrelated file permissions changed: %v, %v", st, err)
					}
				}
			})
		}
	}
}

func TestReceivePreservesExistingDirectory(t *testing.T) {
	for _, symlink := range []bool{false, true} {
		t.Run(fmt.Sprintf("symlink=%t", symlink), func(t *testing.T) {
			dir := t.TempDir()
			target := filepath.Join(dir, "directory")
			if err := os.Mkdir(target, 0o755); err != nil {
				t.Fatal(err)
			}
			dest := target
			if symlink {
				dest = filepath.Join(dir, "link")
				if err := os.Symlink(target, dest); err != nil {
					t.Fatal(err)
				}
			}
			before, err := os.Lstat(dest)
			if err != nil {
				t.Fatal(err)
			}
			f, err := new_remote_file(&Options{Compress: "never"}, &FileTransmissionCommand{
				File_id: "0", Ftype: FileType_regular,
			}, 1)
			if err != nil {
				t.Fatal(err)
			}
			f.expanded_local_path = dest
			if _, err := f.write_data(nil, true); err == nil {
				t.Fatal("Receiving a regular file over a directory should fail")
			}
			after, err := os.Lstat(dest)
			if err != nil || !os.SameFile(before, after) {
				t.Fatalf("Directory or its symlink was replaced: %v", err)
			}
		})
	}
}
