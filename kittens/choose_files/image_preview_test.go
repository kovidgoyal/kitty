package choose_files

import (
	"fmt"
	"image"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
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
func (r fake_preview_renderer) CacheKeyExtra(string) string         { return "" }

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

func TestCmdPreviewConcurrentRendering(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "preview.sh")
	body := "#!/bin/sh\nIFS= read -r content < \"$2\"\nprintf '{\"lines\":[\"%s\",\"%s\"]}\\n' \"$1\" \"$content\"\n"
	if err := os.WriteFile(script, []byte(body), 0o700); err != nil {
		t.Fatal(err)
	}
	// Configured preview commands can have spare capacity shared by workers.
	backing := []string{script, "fixed argument", "unused"}
	renderer := cmd_renderer{cmdline: backing[:2]}
	start := make(chan struct{})
	errors := make(chan error, 2)
	for i := range 2 {
		path := filepath.Join(dir, fmt.Sprintf("file %d λ.txt", i))
		content := fmt.Sprintf("contents of file %d", i)
		if err := os.WriteFile(path, []byte(content+"\n"), 0o600); err != nil {
			t.Fatal(err)
		}
		go func() {
			<-start
			for range 16 {
				_, md, _, err := renderer.Render(path)
				if err != nil {
					errors <- fmt.Errorf("preview %q: %w", path, err)
					return
				}
				result, ok := md.custom.(*CmdResult)
				if !ok || len(result.Lines) != 2 || result.Lines[0] != "fixed argument" || result.Lines[1] != content {
					errors <- fmt.Errorf("preview %q returned %#v, expected %q", path, md.custom, content)
					return
				}
			}
			errors <- nil
		}()
	}
	close(start)
	for range 2 {
		if err := <-errors; err != nil {
			t.Error(err)
		}
	}
	if backing[2] != "unused" {
		t.Errorf("rendering modified shared command arguments: %q", backing)
	}
}

// render_through_cache renders path with renderer the way the UI does, using
// (and populating) the disk cache in cache_dir.
func render_through_cache(t *testing.T, path, cache_dir string, renderer PreviewRenderer) render_data {
	t.Helper()
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	dc, err := disk_cache.NewDiskCache(cache_dir, 1024*1024)
	if err != nil {
		t.Fatal(err)
	}
	p := &ImagePreview{abspath: path, metadata: st, disk_cache: dc, renderer: renderer, WakeupMainThread: func() bool { return true }}
	output := make(chan render_data, 1)
	p.start_rendering(output)
	hd, ok := <-output
	if !ok {
		t.Fatal("no result from preview worker")
	}
	if hd.err != nil {
		t.Fatalf("preview rendering failed: %s", hd.err)
	}
	return hd
}

// count_runs returns the number of lines in path, used to count how many
// times a stub program was run.
func count_runs(t *testing.T, path string) int {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	return strings.Count(string(data), "\n")
}

type fake_ffmpeg struct {
	dir, video, runs_log string
	decodes              *atomic.Int32
}

// The thumbnail content that the image loader recognizes as a valid image.
func (f fake_ffmpeg) valid_thumbnail() string { return f.dir }

// install_fake_ffmpeg puts stub ffmpeg and ffprobe programs first in PATH. The
// ffmpeg stub writes $KITTY_TEST_THUMBNAIL to its output file, then runs
// $KITTY_TEST_FFMPEG_FAILURE, if set. Thumbnails are decoded by a private image
// format registered with the real image loader, so decodes can be counted.
func install_fake_ffmpeg(t *testing.T) fake_ffmpeg {
	t.Helper()
	dir := t.TempDir()
	f := fake_ffmpeg{dir: dir, video: filepath.Join(dir, "video.mp4"), runs_log: filepath.Join(dir, "ffmpeg-runs"), decodes: &atomic.Int32{}}
	thumbnail := image.NewNRGBA(image.Rect(0, 0, 2, 1))
	// The magic is unique even when the test is repeated in the same process.
	image.RegisterFormat("choose-files-test", f.valid_thumbnail(), func(io.Reader) (image.Image, error) {
		f.decodes.Add(1)
		return thumbnail, nil
	}, func(io.Reader) (image.Config, error) {
		return image.Config{ColorModel: thumbnail.ColorModel(), Width: 2, Height: 1}, nil
	})
	scripts := map[string]string{
		"ffprobe": `printf '%s' '{"streams":[{"codec_type":"video","width":2,"height":1}],"format":{"duration":"1.0"}}'`,
		// The output file is the last argument.
		"ffmpeg": `echo run >> "$KITTY_TEST_FFMPEG_RUNS"
for output; do :; done
printf '%s' "$KITTY_TEST_THUMBNAIL" > "$output"
eval "$KITTY_TEST_FFMPEG_FAILURE"`,
	}
	for name, body := range scripts {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("#!/bin/sh\n"+body+"\n"), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(f.video, []byte("not really a video"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("KITTY_TEST_FFMPEG_RUNS", f.runs_log)
	t.Setenv("KITTY_TEST_THUMBNAIL", f.valid_thumbnail())
	t.Setenv("KITTY_TEST_FFMPEG_FAILURE", "")
	return f
}

func check_ffmpeg_metadata(t *testing.T, custom any) {
	t.Helper()
	if info, ok := custom.(*FFMpegMetadata); !ok || info.Format.Duration != "1.0" || len(info.Streams) != 1 || info.Streams[0].Width != 2 {
		t.Errorf("missing video metadata: %#v", custom)
	}
}

func TestFFMpegPreviewRender(t *testing.T) {
	f := install_fake_ffmpeg(t)
	for _, tc := range []struct {
		name, thumbnail, failure string
		want_error               bool
		error_contains           string
		want_decodes             int32
	}{
		{name: "success", thumbnail: f.valid_thumbnail(), want_decodes: 1},
		{name: "ffmpeg-error", thumbnail: f.valid_thumbnail(), failure: "echo 'thumbnail generation failed' >&2; exit 7", want_error: true, error_contains: "thumbnail generation failed"},
		{name: "invalid-thumbnail", thumbnail: "not an image", want_error: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f.decodes.Store(0)
			t.Setenv("KITTY_TEST_THUMBNAIL", tc.thumbnail)
			t.Setenv("KITTY_TEST_FFMPEG_FAILURE", tc.failure)
			data, md, img, err := ffmpeg_renderer(0).Render(f.video)
			if got := f.decodes.Load(); got != tc.want_decodes {
				t.Errorf("decoded thumbnail %d times, expected %d", got, tc.want_decodes)
			}
			if tc.want_error {
				if err == nil || !strings.Contains(err.Error(), tc.error_contains) {
					t.Fatalf("expected an error containing %q, got: %v", tc.error_contains, err)
				}
				if data != nil || img != nil {
					t.Fatal("failed rendering returned an image")
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected render error: %v", err)
			}
			if img == nil || img.Width != 2 || img.Height != 1 || len(img.Frames) != 1 || md.image == nil {
				t.Fatalf("missing rendered image: %#v", img)
			}
			for _, key := range []string{IMAGE_METADATA_KEY, IMAGE_DATA_PREFIX + "0", FFMPEG_METADATA_KEY} {
				if len(data[key]) == 0 {
					t.Errorf("rendered data is missing %s", key)
				}
			}
			check_ffmpeg_metadata(t, md.custom)
		})
	}
}

func TestFFMpegPreviewDiskCache(t *testing.T) {
	f := install_fake_ffmpeg(t)
	cache_dir := filepath.Join(t.TempDir(), "cache")
	first := render_through_cache(t, f.video, cache_dir, ffmpeg_renderer(0))
	check_ffmpeg_metadata(t, first.metadata.custom)
	second := render_through_cache(t, f.video, cache_dir, ffmpeg_renderer(0))
	if n := count_runs(t, f.runs_log); n != 1 {
		t.Errorf("ffmpeg was run %d times, expected the second preview to come from the disk cache", n)
	}
	check_ffmpeg_metadata(t, second.metadata.custom)
	if second.metadata.image == nil || second.metadata.image.Width != 2 || len(second.cached_data[IMAGE_DATA_PREFIX+"0"]) == 0 {
		t.Errorf("cached preview is missing the thumbnail: %#v", second)
	}
}

func TestCmdPreviewDiskCache(t *testing.T) {
	dir := t.TempDir()
	runs_log := filepath.Join(dir, "runs")
	script := filepath.Join(dir, "preview.sh")
	body := fmt.Sprintf("#!/bin/sh\necho run >> '%s'\nprintf '{\"lines\":[\"hello\"],\"title_extra\":\"extra\"}'\n", runs_log)
	if err := os.WriteFile(script, []byte(body), 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "file.txt")
	if err := os.WriteFile(path, []byte("contents"), 0o600); err != nil {
		t.Fatal(err)
	}
	cache_dir := filepath.Join(dir, "cache")
	renderer := cmd_renderer{cmdline: []string{script}}
	for i := range 2 {
		hd := render_through_cache(t, path, cache_dir, renderer)
		if r, ok := hd.metadata.custom.(*CmdResult); !ok || len(r.Lines) != 1 || r.Lines[0] != "hello" || r.TitleExtra != "extra" {
			t.Errorf("preview %d returned unexpected result: %#v", i, hd.metadata.custom)
		}
	}
	if n := count_runs(t, runs_log); n != 1 {
		t.Errorf("preview command was run %d times, expected the second preview to come from the disk cache", n)
	}
}

func TestCmdPreviewDiskCacheSymlinks(t *testing.T) {
	dir := t.TempDir()
	first_target := filepath.Join(dir, "first.txt")
	other_target := filepath.Join(dir, "other.txt")
	mtime := time.Unix(1700000000, 0)
	for _, path := range []string{first_target, other_target} {
		// Give both targets identical sizes and mtimes so that only the resolved
		// target path distinguishes them in the cache key.
		if err := os.WriteFile(path, []byte(filepath.Base(path)+"\n"), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Chtimes(path, mtime, mtime); err != nil {
			t.Fatal(err)
		}
	}
	one, two := filepath.Join(dir, "one.txt"), filepath.Join(dir, "two.txt")
	for _, path := range []string{one, two} {
		if err := os.Symlink(first_target, path); err != nil {
			t.Fatal(err)
		}
	}

	runs_log := filepath.Join(dir, "runs")
	t.Setenv("KITTY_TEST_CMD_PREVIEW_RUNS", runs_log)
	script := filepath.Join(dir, "preview.sh")
	body := `#!/bin/sh
echo run >> "$KITTY_TEST_CMD_PREVIEW_RUNS"
IFS= read -r target < "$1"
printf '{"lines":["%s:%s"]}\n' "${1##*/}" "$target"
`
	if err := os.WriteFile(script, []byte(body), 0o700); err != nil {
		t.Fatal(err)
	}
	cache_dir := filepath.Join(dir, "cache")
	renderer := cmd_renderer{cmdline: []string{script}}
	check := func(path, target string) {
		t.Helper()
		hd := render_through_cache(t, path, cache_dir, renderer)
		want := filepath.Base(path) + ":" + filepath.Base(target)
		if r, ok := hd.metadata.custom.(*CmdResult); !ok || len(r.Lines) != 1 || r.Lines[0] != want {
			t.Errorf("preview for %q should contain %q, got %#v", filepath.Base(path), want, hd.metadata.custom)
		}
	}
	for _, path := range []string{one, two, one, two} {
		check(path, first_target)
	}
	if err := os.Remove(one); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(other_target, one); err != nil {
		t.Fatal(err)
	}
	check(one, other_target)
	check(two, first_target)
	if n := count_runs(t, runs_log); n != 3 {
		t.Errorf("preview command ran %d times, want 3 for the two links and the retargeted link", n)
	}
}

func TestCmdPreviewDiskCacheCommandChange(t *testing.T) {
	dir := t.TempDir()
	runs_log := filepath.Join(dir, "runs")
	t.Setenv("KITTY_TEST_CMD_PREVIEW_RUNS", runs_log)
	script := filepath.Join(dir, "preview.sh")
	body := `#!/bin/sh
echo run >> "$KITTY_TEST_CMD_PREVIEW_RUNS"
printf '{"lines":["%s"]}\n' "$1"
`
	if err := os.WriteFile(script, []byte(body), 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "file.txt")
	if err := os.WriteFile(path, []byte("contents"), 0o600); err != nil {
		t.Fatal(err)
	}
	cache_dir := filepath.Join(dir, "cache")
	for _, arg := range []string{"first", "second", "first"} {
		hd := render_through_cache(t, path, cache_dir, cmd_renderer{cmdline: []string{script, arg}})
		if r, ok := hd.metadata.custom.(*CmdResult); !ok || len(r.Lines) != 1 || r.Lines[0] != arg {
			t.Errorf("preview with argument %q returned: %#v", arg, hd.metadata.custom)
		}
	}
	// Each command has its own cache entry, so switching back to the first
	// command does not run it again.
	if n := count_runs(t, runs_log); n != 2 {
		t.Errorf("preview command ran %d times, want 2", n)
	}
}

func TestCmdPreviewInvalidJSON(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "preview.sh")
	// A type error still populates image, which must not hide the decode error.
	if err := os.WriteFile(script, []byte("#!/bin/sh\nprintf '{\"image\":\"/nonexistent.png\",\"lines\":7}'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	_, _, _, err := cmd_renderer{cmdline: []string{script}}.Render(filepath.Join(dir, "file.txt"))
	if err == nil || !strings.Contains(err.Error(), "could not decode JSON") {
		t.Fatalf("expected a JSON decode error, got: %v", err)
	}
}
