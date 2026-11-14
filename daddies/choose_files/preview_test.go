package choose_files

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

const blocking_timeout = 2 * time.Second

// Wait for result, failing the test if it takes too long. On timeout, the
// FIFO at fifo_path, if any, is opened for writing to unblock any reader
// stuck in open() so that the goroutine producing result does not leak.
func wait_for[T any](t *testing.T, result chan T, fifo_path, what string) (ans T) {
	t.Helper()
	select {
	case ans = <-result:
		return
	case <-time.After(blocking_timeout):
		if fifo_path != "" {
			if f, err := os.OpenFile(fifo_path, os.O_WRONLY|unix.O_NONBLOCK, 0); err == nil {
				f.Close()
			}
		}
		t.Fatalf("%s blocked", what)
	}
	return
}

func make_fifo(t *testing.T, path string) {
	t.Helper()
	if err := unix.Mkfifo(path, 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestTextPreviewFileTypes(t *testing.T) {
	dir := t.TempDir()
	fifo_path := filepath.Join(dir, "pipe.txt")
	make_fifo(t, fifo_path)
	make_fifo(t, filepath.Join(dir, "pipe.png"))
	const content = "ordinary text\n"
	if err := os.WriteFile(filepath.Join(dir, "file.txt"), []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	// A file over the size limit (with an extension not handled by calibre),
	// which must not be previewed as text even via a symlink, whose own size
	// is tiny
	if err := os.WriteFile(filepath.Join(dir, "large.py"), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Truncate(filepath.Join(dir, "large.py"), MAX_TEXT_FILE_SIZE+1); err != nil {
		t.Fatal(err)
	}
	for link, target := range map[string]string{
		"pipe-link.txt": "pipe.txt", "file-link.txt": "file.txt", "large-link.py": "large.py", "broken-link.txt": "missing.txt",
	} {
		if err := os.Symlink(target, filepath.Join(dir, link)); err != nil {
			t.Fatal(err)
		}
	}

	pm := NewPreviewManager(make(chan error, 1), State{}, func() bool { return true })
	for _, tc := range []struct {
		name          string
		metadata_only bool
		fifo          string
	}{
		{"pipe.txt", true, "pipe.txt"}, {"pipe-link.txt", true, "pipe.txt"}, {"pipe.png", true, "pipe.png"},
		{"large.py", true, ""}, {"large-link.py", true, ""}, {"broken-link.txt", true, ""},
		{"file.txt", false, ""}, {"file-link.txt", false, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			path := filepath.Join(dir, tc.name)
			fifo := ""
			if tc.fifo != "" {
				fifo = filepath.Join(dir, tc.fifo)
			}
			info, err := os.Lstat(path)
			if err != nil {
				t.Fatal(err)
			}
			result := make(chan Preview, 1)
			go func() { result <- pm.preview_for(path, info.Mode().Type()) }()
			p := wait_for(t, result, fifo, "preview")
			if tc.metadata_only {
				if _, ok := p.(*MessagePreview); !ok {
					t.Fatalf("expected a metadata preview, got %T", p)
				}
				if fifo == "" {
					return
				}
				// The file can be replaced with a FIFO before highlighting opens it again.
				result := make(chan error, 1)
				go func() {
					_, err := (style_resolver{}).TextForPath(path)
					result <- err
				}()
				if err := wait_for(t, result, fifo, "highlighting"); err == nil {
					t.Fatal("highlighting accepted a named pipe")
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
			wait_for(t, text.highlighted_chan, "", "text highlighting")
		})
	}
}

func TestReadRegularFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "f")
	const content = "0123456789"
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, max_size := range []int64{-1, int64(len(content)), int64(len(content)) + 100} {
		data, err := read_regular_file(path, max_size)
		if err != nil {
			t.Fatalf("max_size=%d: %s", max_size, err)
		}
		if string(data) != content {
			t.Fatalf("max_size=%d: expected %q, got %q", max_size, content, data)
		}
	}
	if _, err := read_regular_file(path, int64(len(content))-1); err == nil || !strings.Contains(err.Error(), "too large") {
		t.Fatalf("expected a too large error, got: %v", err)
	}
	if _, err := read_regular_file(dir, -1); err == nil {
		t.Fatal("reading a directory succeeded")
	}
	if _, err := read_regular_file(filepath.Join(dir, "missing"), -1); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("expected a not exist error, got: %v", err)
	}
}

func TestScanIgnoreFileFIFO(t *testing.T) {
	dir := t.TempDir()
	fifo_path := filepath.Join(dir, ".ignore")
	make_fifo(t, fifo_path)
	if err := os.WriteFile(filepath.Join(dir, "file.txt"), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	ch := make(chan bool)
	s := new_filesystem_scanner(dir, ch, nil)
	done := make(chan bool, 1)
	go func() {
		for range ch {
		}
		done <- true
	}()
	s.Start()
	wait_for(t, done, fifo_path, "scanning a directory with a FIFO ignore file")
	if s.err != nil {
		t.Fatal(s.err)
	}
	if n := s.Len(); n != 1 {
		t.Fatalf("expected one scanned entry, got %d", n)
	}
}
