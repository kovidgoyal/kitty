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
