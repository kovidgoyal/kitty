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

func TestTarExtractHardlinks(t *testing.T) {
	for _, tc := range []struct {
		name, target, link string
	}{
		{"root", "target.txt", "link.txt"},
		{"same_directory", "dir/target.txt", "dir/link.txt"},
		{"cross_directory", "one/target.txt", "two/link.txt"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var buf bytes.Buffer
			tw := tar.NewWriter(&buf)
			for _, hdr := range []tar.Header{
				{Name: tc.target, Mode: 0600},
				{Name: tc.link, Mode: 0600, Typeflag: tar.TypeLink, Linkname: tc.target},
			} {
				if err := tw.WriteHeader(&hdr); err != nil {
					t.Fatal(err)
				}
			}
			if err := tw.Close(); err != nil {
				t.Fatal(err)
			}
			dest := t.TempDir()
			count, err := ExtractAllFromTar(tar.NewReader(&buf), dest)
			if err != nil {
				t.Fatal(err)
			}
			if count != 2 {
				t.Fatalf("Expected two extracted files, got %d", count)
			}
			target, err := os.Stat(filepath.Join(dest, tc.target))
			if err != nil {
				t.Fatal(err)
			}
			link, err := os.Stat(filepath.Join(dest, tc.link))
			if err != nil {
				t.Fatal(err)
			}
			if !os.SameFile(target, link) {
				t.Fatal("Extracted files are not hardlinks")
			}
		})
	}

	t.Run("outside_destination", func(t *testing.T) {
		parent := t.TempDir()
		dest := filepath.Join(parent, "dest")
		if err := os.Mkdir(dest, 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(parent, "outside.txt"), []byte("outside"), 0600); err != nil {
			t.Fatal(err)
		}
		var buf bytes.Buffer
		tw := tar.NewWriter(&buf)
		if err := tw.WriteHeader(&tar.Header{Name: "link.txt", Mode: 0600, Typeflag: tar.TypeLink, Linkname: "../outside.txt"}); err != nil {
			t.Fatal(err)
		}
		if err := tw.Close(); err != nil {
			t.Fatal(err)
		}
		count, err := ExtractAllFromTar(tar.NewReader(&buf), dest)
		if err != nil {
			t.Fatal(err)
		}
		if count != 0 {
			t.Fatalf("Expected external hardlink target to be skipped, got %d extracted files", count)
		}
		if _, err := os.Lstat(filepath.Join(dest, "link.txt")); !os.IsNotExist(err) {
			t.Fatalf("External hardlink target was not skipped: %v", err)
		}
	})
}
