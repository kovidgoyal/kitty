package choose_files

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"github.com/kovidgoyal/kitty/tools/disk_cache"
	"github.com/kovidgoyal/kitty/tools/utils/images"
)

type channelTestRenderer struct{ ImagePreviewRenderer }

func (channelTestRenderer) Render(string) (map[string][]byte, metadata, *images.ImageData, error) {
	return map[string][]byte{"data": []byte("cached")}, metadata{}, nil, nil
}

func (channelTestRenderer) ShowMetadata(*Handler, ShowData) int { return 0 }

func TestImagePreviewChannel(t *testing.T) {
	dc, err := disk_cache.NewDiskCache(t.TempDir(), 0)
	if err != nil {
		t.Fatal(err)
	}
	source := filepath.Join(t.TempDir(), "source")
	if err = os.WriteFile(source, []byte("source"), 0o600); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(source)
	if err != nil {
		t.Fatal(err)
	}
	for range 16 {
		channel := make(chan render_data, 1)
		done := make(chan struct{})
		p := &ImagePreview{
			abspath: source, metadata: info, disk_cache: dc,
			render_channel: channel, renderer: channelTestRenderer{},
			WakeupMainThread: func() bool { close(done); return true },
		}
		go p.start_rendering()
		// Consume the result through Render without waiting for the worker's
		// wakeup, as can happen when the UI redraws while a preview finishes.
		deadline := time.Now().Add(5 * time.Second)
		for len(channel) == 0 {
			if time.Now().After(deadline) {
				t.Fatal("preview worker did not publish its result")
			}
			runtime.Gosched()
		}
		p.Render(&Handler{}, 0, 0, 80, 24)
		<-done
	}
}
