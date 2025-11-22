package choose_files

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"

	"github.com/kovidgoyal/go-parallel"
	"github.com/kovidgoyal/kitty/tools/disk_cache"
	"github.com/kovidgoyal/kitty/tools/icons"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/humanize"
	"github.com/kovidgoyal/kitty/tools/utils/images"
)

const IMAGE_METADATA_KEY = "image-metadata.json"
const IMAGE_DATA_PREFIX = "image-data-"

var dc_size atomic.Int64
var _ = fmt.Print

var preview_cache = sync.OnceValues(func() (*disk_cache.DiskCache, error) {
	cdir := utils.CacheDir()
	cdir = filepath.Join(cdir, "choose-files")
	return disk_cache.NewDiskCache(cdir, dc_size.Load())
})

type ShowData struct {
	abspath             string
	metadata            fs.FileInfo
	x, y, width, height int
	cached_data         map[string]string
	custom_metadata     metadata
}

type PreviewRenderer interface {
	Unmarshall(map[string]string) (any, error)
	Render(string) (map[string][]byte, metadata, *images.ImageData, error)
	ShowMetadata(h *Handler, s ShowData) int
}

type render_data struct {
	cached_data map[string]string
	img         *images.ImageData
	metadata    metadata
	err         error
}

type metadata struct {
	image  *images.SerializableImageMetadata
	custom any
}

type ImagePreview struct {
	abspath               string
	metadata              fs.FileInfo
	disk_cache            *disk_cache.DiskCache
	cached_data           map[string]string
	render_err            Preview
	render_channel        chan render_data
	ready                 atomic.Bool
	source_img            *images.ImageData
	custom_metadata       metadata
	renderer              PreviewRenderer
	file_metadata_preview Preview
	WakeupMainThread      func() bool
}

func (p *ImagePreview) IsValidForColorScheme(bool) bool { return true }
func (p *ImagePreview) IsReady() bool                   { return p.ready.Load() || p.render_channel == nil }

func (p *ImagePreview) Unload() {
	p.source_img = nil
}

func load_image(cached_data map[string]string) (img *images.ImageData, err error) {
	fp := cached_data[IMAGE_METADATA_KEY]
	if fp == "" {
		return nil, fmt.Errorf("missing cached image metadata")
	}
	b, err := os.ReadFile(fp)
	if err != nil {
		return nil, fmt.Errorf("failed to read cached image metadata: %w", err)
	}
	var m images.SerializableImageMetadata
	if err = json.Unmarshal(b, &m); err != nil {
		return nil, fmt.Errorf("failed to decode cached image metadata: %w", err)
	}
	frames := make([][]byte, len(m.Frames))
	for i := range m.Frames {
		path := cached_data[IMAGE_DATA_PREFIX+strconv.Itoa(i)]
		if path == "" {
			return nil, fmt.Errorf("missing cached data for frame: %d", i)
		}
		d, e := os.ReadFile(path)
		if e != nil {
			return nil, fmt.Errorf("failed to read cached image frame %d data: %w", i, e)
		}
		m.Frames[i].Size = len(d)
		frames[i] = d
	}
	return images.ImageFromSerialized(m, frames)
}

func (p *ImagePreview) ensure_source_image() (err error) {
	if p.source_img != nil {
		return
	}
	defer func() {
		if err != nil {
			p.render_err = NewErrorPreview(err)
		}
	}()
	p.source_img, err = load_image(p.cached_data)
	return
}

func (p *ImagePreview) render_image(h *Handler, x, y, width, height int) {
	defer func() {
		if r := recover(); r != nil {
			h.err_chan <- parallel.Format_stacktrace_on_panic(r, 1)
			p.WakeupMainThread()
		}
	}()

	offset := p.renderer.ShowMetadata(h, ShowData{
		abspath: p.abspath, metadata: p.metadata, x: x, y: y, width: width, height: height, cached_data: p.cached_data,
		custom_metadata: p.custom_metadata,
	})
	h.graphics_handler.RenderImagePreview(h, p, x, y+offset, width, height-offset)
}

func (p *ImagePreview) Render(h *Handler, x, y, width, height int) {
	if p.render_channel == nil {
		if p.render_err == nil {
			p.render_image(h, x, y, width, height)
		} else {
			p.render_err.Render(h, x, y, width, height)
		}
		return
	}
	select {
	case hd := <-p.render_channel:
		p.render_channel = nil
		p.cached_data = hd.cached_data
		p.source_img = hd.img
		p.custom_metadata = hd.metadata
		if hd.err != nil {
			p.render_err = NewErrorPreview(fmt.Errorf("Failed to render the preview with error: %w", hd.err))
		}
		p.Render(h, x, y, width, height)
		return
	default:
	}
	if p.file_metadata_preview == nil {
		p.file_metadata_preview = NewFileMetadataPreview(p.abspath, p.metadata)
		m := p.file_metadata_preview.(*MessagePreview)
		m.trailers = append(m.trailers, "", "Rendering image preview, please wait…")
	}
	p.file_metadata_preview.Render(h, x, y, width, height)
}

func (p *ImagePreview) start_rendering() {
	defer func() {
		if r := recover(); r != nil {
			p.render_channel <- render_data{err: parallel.Format_stacktrace_on_panic(r, 1)}
		}
		close(p.render_channel)
		p.ready.Store(true)
		p.WakeupMainThread()
	}()
	key, ans, err := p.disk_cache.GetPath(p.abspath)
	if err != nil {
		p.render_channel <- render_data{err: err}
		return
	}
	if len(ans) > 0 {
		if d := ans[IMAGE_METADATA_KEY]; d != "" {
			if b, err := os.ReadFile(d); err == nil {
				var m images.SerializableImageMetadata
				if err = json.Unmarshal(b, &m); err == nil {
					if cm, err := p.renderer.Unmarshall(ans); err == nil {
						p.render_channel <- render_data{cached_data: ans, metadata: metadata{image: &m, custom: cm}}
						return
					}
				}
			}
		}
	}
	rdata, metadata, img, err := p.renderer.Render(p.abspath)
	if err != nil {
		p.render_channel <- render_data{err: err}
	} else {
		ans, err = p.disk_cache.AddPath(p.abspath, key, rdata)
		if err == nil {
			p.render_channel <- render_data{cached_data: ans, metadata: metadata, img: img}
		} else {
			p.render_channel <- render_data{err: err}
		}
	}
}

type ImagePreviewRenderer uint

func (p ImagePreviewRenderer) Render(abspath string) (ans map[string][]byte, m metadata, img *images.ImageData, err error) {
	if img, err = images.OpenImageFromPath(abspath); err != nil {
		return nil, metadata{}, nil, err
	}
	im, data := img.Serialize()
	ans = make(map[string][]byte, len(data)+1)
	sm, err := json.Marshal(im)
	if err != nil {
		return nil, metadata{}, nil, err
	}
	ans[IMAGE_METADATA_KEY] = sm
	m = metadata{image: &im}
	for i, d := range data {
		key := IMAGE_DATA_PREFIX + strconv.Itoa(i)
		ans[key] = d
	}
	return
}

func (p ImagePreviewRenderer) Unmarshall(map[string]string) (any, error) { return nil, nil }

func (p ImagePreviewRenderer) ShowMetadata(h *Handler, s ShowData) int {
	text := ""
	offset := 0
	if m := s.custom_metadata.image; m != nil {
		text = fmt.Sprintf("%s: %dx%d %s", m.Format_uppercase, m.Width, m.Height, humanize.Bytes(uint64(s.metadata.Size())))
		icon := icons.IconForPath("/a.gif")
		text = icon + "  " + text
		offset += h.render_wrapped_text_in_region(text, s.x, s.y, s.width, s.height, true)
	}
	offset += h.render_wrapped_text_in_region(humanize.Time(s.metadata.ModTime()), s.x, s.y+offset, s.width, s.height-offset, true)
	return offset
}

func NewImagePreview(
	abspath string, metadata fs.FileInfo, opts Settings, WakeupMainThread func() bool, r PreviewRenderer,
) (Preview, error) {
	dc_size.Store(opts.DiskCacheSize())
	ans := &ImagePreview{
		abspath: abspath, metadata: metadata, render_channel: make(chan render_data, 1),
		WakeupMainThread: WakeupMainThread, renderer: r,
	}
	if dc, err := preview_cache(); err != nil {
		return nil, err
	} else {
		ans.disk_cache = dc
	}
	go ans.start_rendering()
	return ans, nil
}
