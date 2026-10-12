package choose_files

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/kovidgoyal/kitty/tools/disk_cache"
	"github.com/kovidgoyal/kitty/tools/utils/images"
)

var _ = fmt.Print

type fake_preview_renderer struct{}

func (r fake_preview_renderer) String() string { return "fake_preview_renderer" }
func (r fake_preview_renderer) Unmarshall(map[string]string) (any, error) {
	return nil, nil
}
func (r fake_preview_renderer) Render(string) (map[string][]byte, metadata, *images.ImageData, error) {
	return map[string][]byte{"rendered": []byte("data")}, metadata{custom: "rendered"}, nil, nil
}
func (r fake_preview_renderer) ShowMetadata(*Handler, ShowData) int { return 0 }

func new_test_image_preview(t *testing.T) *ImagePreview {
	t.Helper()
	tdir := t.TempDir()
	path := filepath.Join(tdir, "image.png")
	if err := os.WriteFile(path, []byte("not really an image"), 0o600); err != nil {
		t.Fatal(err)
	}
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	dc, err := disk_cache.NewDiskCache(filepath.Join(tdir, "cache"), 1024*1024)
	if err != nil {
		t.Fatal(err)
	}
	return &ImagePreview{
		abspath: path, metadata: st, disk_cache: dc, renderer: fake_preview_renderer{},
		render_channel: make(chan render_data, 1), WakeupMainThread: func() bool { return true },
	}
}

// The main thread sets render_channel to nil as soon as it receives the result,
// which can happen before the worker is done. Simulate the worst case where
// this happens before the worker even starts: the worker must still deliver its
// result and close the channel it was given, without panicking or blocking.
func TestImagePreviewWorkerDoesNotUseRenderChannelField(t *testing.T) {
	p := new_test_image_preview(t)
	output := p.render_channel
	p.render_channel = nil
	done := make(chan any, 1)
	go func() {
		defer func() { done <- recover() }()
		p.start_rendering(output)
	}()
	select {
	case r := <-done:
		if r != nil {
			t.Fatalf("worker panicked: %v", r)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("worker did not finish, it is probably blocked sending to a nil channel")
	}
	hd, ok := <-output
	if !ok {
		t.Fatal("worker closed the channel without sending a result")
	}
	if hd.err != nil {
		t.Fatalf("worker failed: %s", hd.err)
	}
	if hd.metadata.custom != "rendered" {
		t.Fatalf("unexpected metadata from worker: %#v", hd.metadata)
	}
	if _, ok = <-output; ok {
		t.Fatal("worker sent more than one result")
	}
	if !p.ready.Load() {
		t.Fatal("worker did not mark the preview as ready")
	}
}

// Consume the result on the main thread concurrently with the worker finishing
// up, as happens in the real program. Run with -race to detect any shared
// state accessed without synchronization.
func TestImagePreviewConcurrentRender(t *testing.T) {
	p := new_test_image_preview(t)
	woken := make(chan bool, 1)
	p.WakeupMainThread = func() bool {
		select {
		case woken <- true:
		default:
		}
		return true
	}
	go p.start_rendering(p.render_channel)
	// Call Render as soon as the result is available, so that it races with
	// the worker closing the channel. Render is only called once the result is
	// buffered, as the "please wait" message needs a real event loop.
	deadline := time.After(10 * time.Second)
	for len(p.render_channel) == 0 {
		select {
		case <-deadline:
			t.Fatal("timed out waiting for the image preview to render")
		case <-time.After(time.Millisecond):
		}
	}
	p.Render(&Handler{}, 0, 0, 80, 24)
	if p.render_channel != nil {
		t.Fatal("Render did not consume the result from the worker")
	}
	if p.render_err != nil {
		t.Fatalf("rendering failed: %#v", p.render_err)
	}
	if p.custom_metadata.custom != "rendered" {
		t.Fatalf("unexpected metadata after render: %#v", p.custom_metadata)
	}
	select {
	case <-woken:
	case <-deadline:
		t.Fatal("worker never woke up the main thread")
	}
	if !p.ready.Load() {
		t.Fatal("worker did not mark the preview as ready")
	}
}
