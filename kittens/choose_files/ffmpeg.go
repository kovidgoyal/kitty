package choose_files

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"github.com/hako/durafmt"
	"github.com/kovidgoyal/imaging/magick"
	"github.com/kovidgoyal/kitty/tools/icons"
	"github.com/kovidgoyal/kitty/tools/utils/humanize"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

const FFMPEG_METADATA_KEY = "ffmpeg-metadata.json"

type ffmpeg_renderer int

var (
	video_width            = 480
	video_fps              = 10
	video_duration         = 5.0
	video_encoding_quality = 75
)

func ffmpeg_thumbnail_cmd(path, outpath string) *exec.Cmd {
	return exec.Command(
		"ffmpeg", "-loglevel", "fatal", "-y", "-i", path, "-t", fmt.Sprintf("%f", video_duration),
		"-vf", fmt.Sprintf("fps=%d,scale=%d:-1:flags=lanczos", video_fps, video_width),
		"-c:v", "libwebp", "-lossless", "0", "-compression_level", "0", "-q:v",
		fmt.Sprintf("%d", video_encoding_quality), "-loop", "0", "-f", "webp", outpath,
	)
}

func ffmpeg_thumbnail(path, tempath string, wg *sync.WaitGroup) (ans *images.ImageData, err error) {
	defer wg.Done()
	cmd := ffmpeg_thumbnail_cmd(path, tempath)
	cmd.Stdin = nil
	cmd.SysProcAttr = &unix.SysProcAttr{Setsid: true}
	var stderr bytes.Buffer
	cmd.Stdout = nil
	cmd.Stderr = &stderr
	if err = cmd.Run(); err != nil {
		return ans, fmt.Errorf("failed to use ffmpeg to render video from %s with error: %w and stderr: %s", path, err, stderr.String())
	}
	ans, err = images.OpenImageFromPath(tempath)
	return
}

type FFMpegFormat struct {
	Start_time string         `json:"start_time"`
	Duration   string         `json:"duration"`
	Tags       map[string]any `json:"tags"`
}

type FFMpegStream struct {
	Codec_type string `json:"codec_type"`
	Width      int    `json:"width"`
	Height     int    `json:"height"`
}

type FFMpegMetadata struct {
	Streams []FFMpegStream `json:"streams"`
	Format  FFMpegFormat   `json:"format"`
}

func ffmpeg_metadata_cmd(path string) *exec.Cmd {
	return exec.Command(
		"ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path,
	)
}

func ffmpeg_metadata(path string, wg *sync.WaitGroup) (ans FFMpegMetadata, err error) {
	defer wg.Done()
	cmd := ffmpeg_metadata_cmd(path)
	cmd.Stdin = nil
	cmd.SysProcAttr = &unix.SysProcAttr{Setsid: true}
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err = cmd.Run(); err != nil {
		return ans, fmt.Errorf("failed to use ffprobe to read metadata from %s with error: %w and stderr: %s", path, err, stderr.String())
	}
	if err = json.Unmarshal(stdout.Bytes(), &ans); err != nil {
		return ans, fmt.Errorf("could not decode JSON response from ffprobe for %s: %w", path, err)
	}
	return
}

func (c ffmpeg_renderer) Render(path string) (m map[string][]byte, mi metadata, img *images.ImageData, err error) {
	wg := sync.WaitGroup{}
	tempfile, err := os.CreateTemp(magick.TempDirInRAMIfPossible(), "kitty-choose-files-*.webp")
	if err != nil {
		return nil, mi, nil, err
	}
	defer func() { _ = os.Remove(tempfile.Name()); tempfile.Close() }()
	var metadata FFMpegMetadata
	var metadata_error error
	wg.Add(1)
	go func() { metadata, metadata_error = ffmpeg_metadata(path, &wg) }()
	wg.Add(1)
	go func() { img, err = ffmpeg_thumbnail(path, tempfile.Name(), &wg) }()
	wg.Wait()
	if metadata_error != nil {
		return nil, mi, nil, metadata_error
	}
	var ip ImagePreviewRenderer
	if m, mi, img, err = ip.Render(tempfile.Name()); err != nil {
		return
	}
	mi.custom = &metadata

	return
}

func (c ffmpeg_renderer) Unmarshall(m map[string]string) (any, error) {
	data, err := os.ReadFile(m[FFMPEG_METADATA_KEY])
	if err != nil {
		return nil, err
	}
	var ans FFMpegMetadata
	if err = json.Unmarshal(data, &ans); err != nil {
		return nil, err
	}
	return &ans, nil
}

func (c ffmpeg_renderer) ShowMetadata(h *Handler, s ShowData) (offset int) {
	w := func(text string, center bool) {
		if s.height > offset {
			offset += h.render_wrapped_text_in_region(text, s.x, s.y+offset, s.width, s.height-offset, center)
		}
	}
	ext := filepath.Ext(s.abspath)
	text := fmt.Sprintf("%s: %s", ext, humanize.Bytes(uint64(s.metadata.Size())))
	r := s.custom_metadata.custom.(*FFMpegMetadata)
	icon := icons.IconForPath(s.abspath)
	var width, height int
	for _, s := range r.Streams {
		if s.Width > 0 && s.Height > 0 {
			width, height = s.Width, s.Height
			break
		}
	}
	text += fmt.Sprintf(" %dx%d", width, height)
	w(icon+"  "+text, true)
	st := humanize.Time(s.metadata.ModTime())
	if d, perr := strconv.ParseFloat(r.Format.Duration, 64); perr == nil {
		duration := time.Duration(d * float64(time.Second))
		st += fmt.Sprintf(", %s", durafmt.Parse(duration).LimitFirstN(1).String())
	}
	w(st, true)
	return
}

func (c ffmpeg_renderer) String() string {
	return "FFMpeg"
}

func NewFFMpegPreview(
	abspath string, metadata fs.FileInfo, opts Settings, WakeupMainThread func() bool,
) Preview {
	c := ffmpeg_renderer(0)
	if ans, err := NewImagePreview(abspath, metadata, opts, WakeupMainThread, c); err == nil {
		return ans
	} else {
		return NewErrorPreview(err)
	}
}
