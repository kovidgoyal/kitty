package utils

import (
	"archive/tar"
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
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

type tar_entry struct {
	name, body, linkname string
	typeflag             byte
}

func make_tar(t *testing.T, entries ...tar_entry) *tar.Reader {
	t.Helper()
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	for _, e := range entries {
		typeflag := e.typeflag
		if typeflag == 0 {
			typeflag = tar.TypeReg
		}
		hdr := tar.Header{Name: e.name, Mode: 0600, Typeflag: typeflag, Linkname: e.linkname, Size: int64(len(e.body))}
		if err := tw.WriteHeader(&hdr); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write([]byte(e.body)); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	return tar.NewReader(&buf)
}

func assert_same_file(t *testing.T, a, b string) {
	t.Helper()
	sa, err := os.Stat(a)
	if err != nil {
		t.Fatal(err)
	}
	sb, err := os.Stat(b)
	if err != nil {
		t.Fatal(err)
	}
	if !os.SameFile(sa, sb) {
		t.Fatalf("%s and %s are not hardlinks", a, b)
	}
}

func assert_file_contents(t *testing.T, path, expected string) {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != expected {
		t.Fatalf("Contents of %s not as expected: %#v != %#v", path, string(data), expected)
	}
}

func TestTarExtractHardlinks(t *testing.T) {
	for _, tc := range []struct {
		name, target, link string
	}{
		{"root", "target.txt", "link.txt"},
		{"same_directory", "dir/target.txt", "dir/link.txt"},
		{"cross_directory", "one/target.txt", "two/link.txt"},
		{"dot_slash_prefix", "./dir/target.txt", "./dir/link.txt"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dest := t.TempDir()
			count, err := ExtractAllFromTar(make_tar(t,
				tar_entry{name: tc.target},
				tar_entry{name: tc.link, typeflag: tar.TypeLink, linkname: tc.target},
			), dest)
			if err != nil {
				t.Fatal(err)
			}
			if count != 2 {
				t.Fatalf("Expected two extracted files, got %d", count)
			}
			assert_same_file(t, filepath.Join(dest, tc.target), filepath.Join(dest, tc.link))
		})
	}

	t.Run("through_symlinked_directory", func(t *testing.T) {
		dest := t.TempDir()
		if _, err := ExtractAllFromTar(make_tar(t,
			tar_entry{name: "real/target.txt"},
			tar_entry{name: "alias", typeflag: tar.TypeSymlink, linkname: "real"},
			tar_entry{name: "two/link.txt", typeflag: tar.TypeLink, linkname: "alias/target.txt"},
		), dest); err != nil {
			t.Fatal(err)
		}
		assert_same_file(t, filepath.Join(dest, "real/target.txt"), filepath.Join(dest, "two/link.txt"))
	})

	t.Run("to_symlink", func(t *testing.T) {
		dest := t.TempDir()
		if _, err := ExtractAllFromTar(make_tar(t,
			tar_entry{name: "target.txt", body: "target"},
			tar_entry{name: "sym", typeflag: tar.TypeSymlink, linkname: "target.txt"},
			tar_entry{name: "dir/link", typeflag: tar.TypeLink, linkname: "sym"},
		), dest); err != nil {
			t.Fatal(err)
		}
		link := filepath.Join(dest, "dir/link")
		st, err := os.Lstat(link)
		if err != nil {
			t.Fatal(err)
		}
		if st.Mode()&fs.ModeSymlink == 0 {
			t.Fatalf("Hardlink to symlink is not a symlink: %v", st.Mode())
		}
		assert_file_contents(t, link, "target")
	})

	t.Run("duplicate_entries", func(t *testing.T) {
		dest := t.TempDir()
		if _, err := ExtractAllFromTar(make_tar(t,
			tar_entry{name: "a", body: "one"},
			tar_entry{name: "b", typeflag: tar.TypeLink, linkname: "a"},
			tar_entry{name: "b", typeflag: tar.TypeLink, linkname: "a"},
			tar_entry{name: "a", typeflag: tar.TypeLink, linkname: "a"},
			tar_entry{name: "c", typeflag: tar.TypeLink, linkname: "a"},
			tar_entry{name: "c", body: "two"},
			tar_entry{name: "s", typeflag: tar.TypeSymlink, linkname: "a"},
			tar_entry{name: "s", typeflag: tar.TypeSymlink, linkname: "c"},
		), dest); err != nil {
			t.Fatal(err)
		}
		assert_same_file(t, filepath.Join(dest, "a"), filepath.Join(dest, "b"))
		// replacing a hardlinked file must not change the other links
		assert_file_contents(t, filepath.Join(dest, "a"), "one")
		assert_file_contents(t, filepath.Join(dest, "c"), "two")
		assert_file_contents(t, filepath.Join(dest, "s"), "two")
	})

	outside := func(t *testing.T, entries ...tar_entry) {
		parent := t.TempDir()
		dest := filepath.Join(parent, "dest")
		if err := os.Mkdir(dest, 0700); err != nil {
			t.Fatal(err)
		}
		outside_file := filepath.Join(parent, "outside.txt")
		if err := os.WriteFile(outside_file, []byte("outside"), 0600); err != nil {
			t.Fatal(err)
		}
		for i := range entries {
			entries[i].linkname = strings.ReplaceAll(entries[i].linkname, "PARENT", parent)
		}
		if _, err := ExtractAllFromTar(make_tar(t, entries...), dest); err == nil {
			t.Fatal("Hardlink to file outside destination did not fail")
		}
		if _, err := os.Lstat(filepath.Join(dest, "link.txt")); !os.IsNotExist(err) {
			t.Fatalf("Hardlink to file outside destination was created: %v", err)
		}
		st, err := os.Stat(outside_file)
		if err != nil {
			t.Fatal(err)
		}
		if st.Mode().Perm() != 0600 {
			t.Fatalf("Permissions of file outside destination were changed: %v", st.Mode())
		}
	}
	t.Run("outside_destination", func(t *testing.T) {
		outside(t, tar_entry{name: "link.txt", typeflag: tar.TypeLink, linkname: "../outside.txt"})
	})
	t.Run("outside_destination_absolute", func(t *testing.T) {
		outside(t, tar_entry{name: "link.txt", typeflag: tar.TypeLink, linkname: "PARENT/outside.txt"})
	})
	t.Run("outside_destination_via_symlink", func(t *testing.T) {
		outside(t,
			tar_entry{name: "s", typeflag: tar.TypeSymlink, linkname: "PARENT"},
			tar_entry{name: "link.txt", typeflag: tar.TypeLink, linkname: "s/outside.txt"},
		)
	})
}
