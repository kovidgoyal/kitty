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

type ImagePreview struct {
	abspath, cache_key string
	disk_cache         *disk_cache.DiskCache
}

func (p ImagePreview) IsValidForColorScheme(bool) bool { return true }

func (p ImagePreview) Render(h *Handler, x, y, width, height int) {
	offset := 0
	offset += h.render_wrapped_text_in_region("Rendering image, please wait...", x, y, width, height, true)
}

func NewImagePreview(abspath string, metadata fs.FileInfo, opts Settings) (Preview, error) {
	dc_size.Store(opts.DiskCacheSize())
	ans := &ImagePreview{abspath: abspath}
	if dc, err := preview_cache(); err != nil {
		return nil, err
	} else {
		ans.disk_cache = dc
	}
	if key, err := disk_cache.KeyForPath(abspath); err != nil {
		return nil, err
	} else {
		ans.cache_key = key
	}
	return ans, nil
}
