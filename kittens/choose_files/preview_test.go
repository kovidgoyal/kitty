package choose_files

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

func TestTextPreviewFileTypes(t *testing.T) {
	dir := t.TempDir()
	fifo_path := filepath.Join(dir, "pipe.txt")
	if err := unix.Mkfifo(fifo_path, 0o600); err != nil {
		t.Fatal(err)
	}
	const content = "ordinary text\n"
	if err := os.WriteFile(filepath.Join(dir, "file.txt"), []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	for link, target := range map[string]string{"pipe-link.txt": "pipe.txt", "file-link.txt": "file.txt"} {
		if err := os.Symlink(target, filepath.Join(dir, link)); err != nil {
			t.Fatal(err)
		}
	}

	pm := NewPreviewManager(make(chan error, 1), State{}, func() bool { return true })
	for _, tc := range []struct {
		name string
		fifo bool
	}{
		{"pipe.txt", true}, {"pipe-link.txt", true},
		{"file.txt", false}, {"file-link.txt", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			path := filepath.Join(dir, tc.name)
			info, err := os.Lstat(path)
			if err != nil {
				t.Fatal(err)
			}
			result := make(chan Preview, 1)
			go func() { result <- pm.preview_for(path, info.Mode().Type()) }()
			var p Preview
			select {
			case p = <-result:
			case <-time.After(2 * time.Second):
				t.Fatal("preview blocked")
			}
			if tc.fifo {
				if _, ok := p.(*MessagePreview); !ok {
					t.Fatalf("expected a metadata preview, got %T", p)
				}
				// The file can be replaced with a FIFO before highlighting opens it again.
				result := make(chan error, 1)
				go func() {
					_, err := (style_resolver{}).TextForPath(path)
					result <- err
				}()
				select {
				case err := <-result:
					if err == nil {
						t.Fatal("highlighting accepted a named pipe")
					}
				case <-time.After(2 * time.Second):
					t.Fatal("highlighting blocked on a named pipe")
				}
				return
			}
			text, ok := p.(*TextFilePreview)
			if !ok {
				t.Fatalf("expected a text preview, got %T", p)
			}
			if text.plain_text != content {
				t.Fatalf("expected %q, got %q", content, text.plain_text)
			}
			select {
			case <-text.highlighted_chan:
			case <-time.After(2 * time.Second):
				t.Fatal("text highlighting blocked")
			}
		})
	}
}
