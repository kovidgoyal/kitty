package images

import (
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

var one_pixel_gray_png = []byte{137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 1, 0, 0, 0, 1, 8, 0, 0, 0, 0, 58, 126, 155, 85, 0, 0, 0, 10, 73, 68, 65, 84, 120, 1, 99, 176, 5, 0, 0, 63, 0, 62, 18, 174, 200, 16, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130}

func TestRenderCache(t *testing.T) {
	chmtime_after_creation = true
	epoch := time.Now()
	now_implementation = func() time.Time {
		epoch = epoch.Add(3 * time.Second)
		return epoch
	}
	defer func() {
		chmtime_after_creation = false
		now_implementation = time.Now
	}()
	tmp := t.TempDir()
	cdir := filepath.Join(tmp, "cache")
	if err := os.Mkdir(cdir, 0777); err != nil {
		t.Fatal(err)
	}
	srcs := make([]string, 0, 5)
	outputs := make([]string, 0, 5)
	const max_cache_entries = 2
	for i := range max_cache_entries * 2 {
		name := fmt.Sprintf(`%d.png`, i)
		src_path := filepath.Join(tmp, name)
		srcs = append(srcs, src_path)
		if err := os.WriteFile(src_path, one_pixel_gray_png, 0644); err != nil {
			t.Fatal(err)
		}
		output_path, err := render_image(src_path, cdir, max_cache_entries)
		if err != nil {
			t.Fatal(err)
		}
		outputs = append(outputs, output_path)
		if entries, err := os.ReadDir(cdir); err != nil {
			t.Fatal(err)
		} else if len(entries) > max_cache_entries {
			t.Fatalf("Too many files in cache dir %d > %d", len(entries), max_cache_entries)
		}
	}
	exists := func(path string) bool {
		_, err := os.Stat(path)
		return err == nil
	}
	mtime := func(path string) time.Time {
		ans, err := os.Stat(path)
		if err != nil {
			t.Fatal(err)
		}
		return ans.ModTime()
	}
	for i, x := range outputs[len(outputs)-max_cache_entries:] {
		if !exists(x) {
			t.Fatalf("The %d cache entry does not exist", max_cache_entries+i)
		}
	}
	o := outputs[len(outputs)-max_cache_entries:]
	if mtime(o[0]).After(mtime(o[1])) {
		t.Fatalf("The mtimes are not monotonic")
	}
	s := srcs[len(srcs)-max_cache_entries:]
	output_path, err := render_image(s[0], cdir, max_cache_entries)
	if err != nil {
		t.Fatal(err)
	}
	if output_path != o[0] {
		t.Fatalf("Output path change on rerun")
	}
	if mtime(o[1]).After(mtime(o[0])) || mtime(o[1]).Equal(mtime(o[0])) {
		t.Fatalf("The mtime was not updated")
	}
	data, err := os.ReadFile(output_path)
	if err != nil {
		t.Fatal(err)
	}
	if len(data) != 12 {
		t.Fatalf("unexpected data length: %d != %d", len(data), 12)
	}
	if width, height := binary.LittleEndian.Uint32(data), binary.LittleEndian.Uint32(data[4:]); width != 1 || height != 1 {
		t.Fatalf("unexpected dimensions: %dx%d", width, height)
	}
	if diff := cmp.Diff(data[8:], []byte{61, 61, 61, 255}); diff != "" {
		t.Fatalf("unexpected pixel: %s", diff)
	}
}
