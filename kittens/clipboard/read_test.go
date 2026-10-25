// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"bytes"
	"fmt"
	"image"
	"image/png"
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestClipboardOutputCommitAtomic(t *testing.T) {
	dest := filepath.Join(t.TempDir(), "output")
	old_data := bytes.Repeat([]byte("old contents\n"), 1024)
	new_data := bytes.Repeat([]byte("new contents\n"), 1024)
	if err := os.WriteFile(dest, old_data, 0o640); err != nil {
		t.Fatal(err)
	}

	started, stop := make(chan struct{}), make(chan struct{})
	result := make(chan error, 1)
	go func() {
		data, err := os.ReadFile(dest)
		close(started)
		for {
			if err != nil {
				result <- fmt.Errorf("Concurrent read failed: %w", err)
				return
			}
			if !bytes.Equal(data, old_data) && !bytes.Equal(data, new_data) {
				result <- fmt.Errorf("Concurrent read returned incomplete contents: %q", data)
				return
			}
			select {
			case <-stop:
				result <- nil
				return
			default:
			}
			data, err = os.ReadFile(dest)
		}
	}()
	<-started
	t.Cleanup(func() {
		close(stop)
		if err := <-result; err != nil {
			t.Error(err)
		}
	})

	for i := range 100 {
		data := new_data
		if i%2 != 0 {
			data = old_data
		}
		output := Output{arg: dest}
		output.add_data(data)
		if output.err != nil {
			t.Fatal(output.err)
		}
		temp_name := output.dest.Name()
		output.commit()
		if output.err != nil {
			t.Fatal(output.err)
		}
		actual, err := os.ReadFile(dest)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(actual, data) {
			t.Fatal("Committed file has incorrect contents")
		}
		if st, err := os.Stat(dest); err != nil {
			t.Fatal(err)
		} else if st.Mode().Perm() != 0o640 {
			t.Fatalf("Committed file has incorrect permissions: %o", st.Mode().Perm())
		}
		if _, err := os.Stat(temp_name); !os.IsNotExist(err) {
			t.Fatalf("Temporary file still exists after commit: %v", err)
		}
	}
}

func list_dir(t *testing.T, dir string) (ans []string) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		ans = append(ans, e.Name())
	}
	return
}

func TestClipboardOutputCommitFailure(t *testing.T) {
	dir := t.TempDir()
	// Renaming a file over a non-empty directory fails even when running as root
	dest := filepath.Join(dir, "output")
	if err := os.MkdirAll(filepath.Join(dest, "child"), 0o755); err != nil {
		t.Fatal(err)
	}
	output := Output{arg: dest}
	defer output.cleanup()
	output.add_data([]byte("new contents"))
	if output.err != nil {
		t.Fatal(output.err)
	}
	output.commit()
	if output.err == nil {
		t.Fatal("Expected commit to fail when destination is a non-empty directory")
	}
	if st, err := os.Stat(filepath.Join(dest, "child")); err != nil || !st.IsDir() {
		t.Fatalf("Original destination changed after failed commit: %v", err)
	}
	if names := list_dir(t, dir); !slices.Equal(names, []string{"output"}) {
		t.Fatalf("Stray files left behind after failed commit: %v", names)
	}
}

func TestClipboardOutputCommitNewFile(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "output")
	output := Output{arg: dest}
	output.add_data([]byte("new contents"))
	output.commit()
	if output.err != nil {
		t.Fatal(output.err)
	}
	if actual, err := os.ReadFile(dest); err != nil || string(actual) != "new contents" {
		t.Fatalf("Incorrect contents in new file: %q %v", actual, err)
	}
	if names := list_dir(t, dir); !slices.Equal(names, []string{"output"}) {
		t.Fatalf("Stray files left behind after commit: %v", names)
	}
}

func TestClipboardOutputCommitSymlink(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "target")
	dest := filepath.Join(dir, "link")
	if err := os.WriteFile(target, []byte("old contents"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, dest); err != nil {
		t.Fatal(err)
	}
	output := Output{arg: dest}
	output.add_data([]byte("new contents"))
	output.commit()
	if output.err != nil {
		t.Fatal(output.err)
	}
	if st, err := os.Lstat(dest); err != nil || st.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("Symlink at destination was replaced: %v", err)
	}
	if actual, err := os.ReadFile(target); err != nil || string(actual) != "new contents" {
		t.Fatalf("Symlink target not updated: %q %v", actual, err)
	}
}

func TestClipboardOutputCommitDanglingSymlink(t *testing.T) {
	for _, link_type := range []string{"absolute", "relative"} {
		for _, data_type := range []string{"text", "image"} {
			t.Run(link_type+"/"+data_type, func(t *testing.T) {
				dir := t.TempDir()
				target := filepath.Join(dir, "target")
				dest := filepath.Join(dir, "link")
				link := target
				if link_type == "relative" {
					link = "target"
				}
				if err := os.Symlink(link, dest); err != nil {
					t.Fatal(err)
				}
				data := []byte("new contents")
				output := Output{arg: dest}
				defer output.cleanup()
				if data_type == "image" {
					var buf bytes.Buffer
					if err := png.Encode(&buf, image.NewRGBA(image.Rect(0, 0, 2, 3))); err != nil {
						t.Fatal(err)
					}
					data = buf.Bytes()
					output.image_needs_conversion = true
					output.mime_type = "image/jpeg"
				}
				output.add_data(data)
				output.commit()
				if output.err != nil {
					t.Fatal(output.err)
				}
				if actual, err := os.Readlink(dest); err != nil || actual != link {
					t.Errorf("Symlink at destination changed: %q %v", actual, err)
				}
				actual, err := os.ReadFile(target)
				if err != nil {
					t.Fatalf("Symlink target not created: %v", err)
				}
				if data_type == "image" {
					img, format, err := image.Decode(bytes.NewReader(actual))
					if err != nil {
						t.Fatal(err)
					}
					if format != "jpeg" || img.Bounds() != image.Rect(0, 0, 2, 3) {
						t.Fatalf("Incorrect converted image: %s %v", format, img.Bounds())
					}
				} else if !bytes.Equal(actual, data) {
					t.Fatalf("Incorrect contents in symlink target: %q", actual)
				}
				if names := list_dir(t, dir); !slices.Equal(names, []string{"link", "target"}) {
					t.Fatalf("Stray files left behind after commit: %v", names)
				}
			})
		}
	}
}

func TestClipboardOutputImageEncodeFailure(t *testing.T) {
	dest := filepath.Join(t.TempDir(), "output")
	old_data := []byte("old contents")
	if err := os.WriteFile(dest, old_data, 0o600); err != nil {
		t.Fatal(err)
	}
	var png_data bytes.Buffer
	if err := png.Encode(&png_data, image.NewRGBA(image.Rect(0, 0, 1, 1))); err != nil {
		t.Fatal(err)
	}
	output := Output{arg: dest, image_needs_conversion: true, mime_type: "image/x-unsupported"}
	defer output.cleanup()
	output.add_data(png_data.Bytes())
	if output.err != nil {
		t.Fatal(output.err)
	}
	output.commit()
	if output.err == nil {
		t.Fatal("Expected commit to fail with an unsupported image type")
	}
	if actual, err := os.ReadFile(dest); err != nil || !bytes.Equal(actual, old_data) {
		t.Fatalf("Original destination changed after failed image encode: %q %v", actual, err)
	}
}
