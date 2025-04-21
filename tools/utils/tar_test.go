package utils

import (
	"archive/tar"
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestTarExtract(t *testing.T) {
	tdir := t.TempDir()
	a, b := filepath.Join(tdir, "a"), filepath.Join(tdir, "b")
	if err := os.Mkdir(a, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(b, 0700); err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	var files = []struct {
		name, body string
	}{
		{"s/one.txt", "This archive contains some text files."},
		{"b", b},
		{"b/two.txt", "Get animal handling license."},
		{"../b/three.txt", "Get animal handling license."},
		{"nested/dir/", ""},
	}
	for _, file := range files {
		hdr := &tar.Header{
			Name: file.name,
			Mode: 0600,
			Size: int64(len(file.body)),
		}
		if file.name == "b" {
			hdr.Linkname = file.body
			hdr.Typeflag = tar.TypeSymlink
			hdr.Size = 0
		}
		if err := tw.WriteHeader(hdr); err != nil {
			t.Fatal(err)
		}
		if hdr.Typeflag != tar.TypeSymlink && len(file.body) > 0 {
			if _, err := tw.Write([]byte(file.body)); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	tr := tar.NewReader(&buf)
	count, err := ExtractAllFromTar(tr, a)
	if err != nil {
		t.Fatal(err)
	}
	if count != len(files)-2 {
		t.Fatalf("Incorrect count of extracted files: %d != %d", count, len(files)-2)
	}
	entries := []string{}
	if err = fs.WalkDir(os.DirFS(tdir), ".", func(path string, d fs.DirEntry, err error) error {
		entries = append(entries, path)
		return err
	},
	); err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]string{".", "a", "a/b", "a/nested", "a/nested/dir", "a/s", "a/s/one.txt", "b"}, entries); diff != "" {
		t.Fatalf("Directory contents not as expected: %s", diff)
	}
}
