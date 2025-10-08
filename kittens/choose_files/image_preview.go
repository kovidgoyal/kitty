package choose_files

import (
	"fmt"
	"io/fs"
	"path/filepath"
	"sync"
	"sync/atomic"

	"github.com/kovidgoyal/kitty/tools/disk_cache"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

var dc_size atomic.Int64

var preview_cache = sync.OnceValues(func() (*disk_cache.DiskCache, error) {
	cdir := utils.CacheDir()
	cdir = filepath.Join(cdir, "choose-files")
	return disk_cache.NewDiskCache(cdir, dc_size.Load())
})

type PreviewRenderer interface {
	Render(string) (map[string][]byte, error)
	ShowMetadata(h *Handler, abspath string, metadata fs.FileInfo, x, y, width, height int, cached_data map[string]string) int
}

type render_data struct {
	cached_data map[string]string
	err         error
}

type ImagePreview struct {
	abspath               string
	metadata              fs.FileInfo
	disk_cache            *disk_cache.DiskCache
	cached_data           map[string]string
	render_err            Preview
	render_channel        chan render_data
	renderer              PreviewRenderer
	file_metadata_preview Preview
	WakeupMainThread      func() bool
}

func (p ImagePreview) IsValidForColorScheme(bool) bool { return true }

func (p ImagePreview) Render(h *Handler, x, y, width, height int) {
	if p.render_channel == nil {
		if p.render_err == nil {
			y += p.renderer.ShowMetadata(h, p.abspath, p.metadata, x, y, width, height, p.cached_data)
		} else {
			p.render_err.Render(h, x, y, width, height)
		}
		return
	}
	select {
	case hd := <-p.render_channel:
		p.render_channel = nil
		p.cached_data = hd.cached_data
		p.render_err = NewErrorPreview(fmt.Errorf("Failed to render the preview with error: %w", hd.err))
		p.Render(h, x, y, width, height)
		return
	default:
	}
	if p.file_metadata_preview == nil {
		p.file_metadata_preview = NewFileMetadataPreview(p.abspath, p.metadata)
	}
	p.file_metadata_preview.Render(h, x, y, width, height)
}

func (p *ImagePreview) start_rendering() {
	defer func() {
		p.WakeupMainThread()
	}()
	key, ans, err := p.disk_cache.GetPath(p.abspath)
	if err != nil {
		p.render_channel <- render_data{nil, err}
	}
	if len(ans) > 0 {
		p.render_channel <- render_data{ans, nil}
		return
	}
	rdata, err := p.renderer.Render(p.abspath)
	if err != nil {
		p.render_channel <- render_data{nil, err}
	} else {
		ans, err = p.disk_cache.AddPath(p.abspath, key, rdata)
		p.render_channel <- render_data{utils.IfElse(err == nil, ans, nil), err}
	}
}

type ImagePreviewRenderer uint

func (p ImagePreviewRenderer) Render(abspath string) (ans map[string][]byte, err error) {
	return
}

func (p ImagePreviewRenderer) ShowMetadata(h *Handler, abspath string, metadata fs.FileInfo, x, y, width, height int, cached_data map[string]string) int {
	return 0
}

func NewImagePreview(
	abspath string, metadata fs.FileInfo, opts Settings, WakeupMainThread func() bool, r PreviewRenderer,
) (Preview, error) {
	dc_size.Store(opts.DiskCacheSize())
	ans := &ImagePreview{
		abspath: abspath, metadata: metadata, render_channel: make(chan render_data),
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
