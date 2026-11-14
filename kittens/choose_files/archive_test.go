package choose_files

import (
	"archive/zip"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"
)

var _ = fmt.Print

func new_test_archive_preview(t *testing.T, names ...string) (*archive_preview, *MessagePreview) {
	t.Helper()
	if len(names) == 0 {
		names = []string{"a.txt", "dir/b.txt"}
	}
	path := filepath.Join(t.TempDir(), "test.zip")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(f)
	for _, name := range names {
		w, err := zw.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = w.Write([]byte(name)); err != nil {
			t.Fatal(err)
		}
	}
	if err = zw.Close(); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	mp := NewFileMetadataPreview(path, st)
	p := &archive_preview{
		path: path, metadata: st, ch: make(chan *MessagePreview, 1), mp: mp,
		WakeupMainThread: func() bool { return true },
	}
	return p, mp
}

// Run the archive preview worker, failing the test if it panics, blocks or
// does not send exactly one result.
func run_archive_preview_worker(t *testing.T, p *archive_preview, base *MessagePreview) *MessagePreview {
	t.Helper()
	output := p.ch
	woken := false
	p.WakeupMainThread = func() bool { woken = true; return true }
	done := make(chan any, 1)
	go func() {
		defer func() { done <- recover() }()
		p.render(output, base)
	}()
	select {
	case r := <-done:
		if r != nil {
			t.Fatalf("worker panicked: %v", r)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("worker did not finish")
	}
	result, ok := <-output
	if !ok || result == nil {
		t.Fatal("worker did not send a result")
	}
	if _, ok = <-output; ok {
		t.Fatal("worker sent more than one result")
	}
	if !woken {
		t.Fatal("worker did not wake up the main thread")
	}
	return result
}

func TestArchivePreviewListsContents(t *testing.T) {
	p, base := new_test_archive_preview(t)
	result := run_archive_preview_worker(t, p, base)
	for _, name := range []string{"a.txt", "dir/b.txt"} {
		if !slices.Contains(result.trailers, name) {
			t.Fatalf("archive preview does not list %#v: %#v", name, result.trailers)
		}
	}
}

// A panic in the worker goroutine must be reported in the preview rather than
// crashing the whole program. A nil base preview makes the worker panic.
func TestArchivePreviewWorkerPanic(t *testing.T) {
	p, _ := new_test_archive_preview(t)
	result := run_archive_preview_worker(t, p, nil)
	if !strings.Contains(strings.Join(result.trailers, "\n"), "Failed to read the archive") {
		t.Fatalf("archive preview does not report the panic: %#v", result.trailers)
	}
}

// Names of archive members are untrusted and must not be able to inject
// escape codes into the terminal.
func TestArchivePreviewSanitizesNames(t *testing.T) {
	evil := "x\x1b]52;c;aGFja2Vk\x07\ny.txt"
	p, base := new_test_archive_preview(t, evil)
	result := run_archive_preview_worker(t, p, base)
	for _, line := range result.trailers {
		if strings.ContainsAny(line, "\x1b\x07\n") {
			t.Fatalf("archive preview contains unsanitized name: %#v", line)
		}
	}
	if expected := "x␛]52;c;aGFja2Vk␇␤y.txt"; !slices.Contains(result.trailers, expected) {
		t.Fatalf("archive preview does not list %#v: %#v", expected, result.trailers)
	}
}

func TestArchivePreviewLimitsEntries(t *testing.T) {
	names := make([]string, 2*max_archive_entries)
	for i := range names {
		names[i] = fmt.Sprintf("%d.txt", i)
	}
	p, base := new_test_archive_preview(t, names...)
	result := run_archive_preview_worker(t, p, base)
	if n := len(result.trailers) - len(base.trailers); n != max_archive_entries {
		t.Fatalf("archive preview has %d entries, expected %d", n, max_archive_entries)
	}
	if !slices.Contains(result.trailers, "0.txt") || slices.Contains(result.trailers, names[max_archive_entries]) {
		t.Fatalf("archive preview has the wrong entries: %#v", result.trailers)
	}
}
