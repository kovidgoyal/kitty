// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package graphics

import (
	"errors"
	"fmt"
	"sync"
	"sync/atomic"

	"kitty/tools/tui/loop"
	"kitty/tools/utils/images"

	"golang.org/x/exp/maps"
)

var _ = fmt.Print

type Size struct{ Width, Height int }

type Image struct {
	src struct {
		path   string
		data   *images.ImageData
		size   Size
		loaded bool
	}
	renderings map[Size]*images.ImageData
	err        error
}

type ImageCollection struct {
	Shm_supported, Files_supported atomic.Bool
	mutex                          sync.Mutex

	images map[string]*Image
}

var ErrNotFound = errors.New("not found")

func (self *ImageCollection) GetSizeIfAvailable(key string, page_size Size) (Size, error) {
	if !self.mutex.TryLock() {
		return Size{}, ErrNotFound
	}
	defer self.mutex.Unlock()
	img := self.images[key]
	if img == nil {
		return Size{}, ErrNotFound
	}
	ans := img.renderings[page_size]
	if ans == nil {
		return Size{}, ErrNotFound
	}
	return Size{ans.Width, ans.Height}, img.err
}

func (self *ImageCollection) ResolutionOf(key string) Size {
	if !self.mutex.TryLock() {
		return Size{-1, -1}
	}
	defer self.mutex.Unlock()
	i := self.images[key]
	if i == nil {
		return Size{-2, -2}
	}
	return i.src.size
}

func (self *ImageCollection) AddPaths(paths ...string) {
	self.mutex.Lock()
	defer self.mutex.Unlock()
	for _, path := range paths {
		if self.images[path] == nil {
			i := &Image{}
			i.src.path = path
			self.images[path] = i
		}
	}
}

func (self *Image) ResizeForPageSize(width, height int) {
	sz := Size{width, height}
	if self.renderings[sz] != nil {
		return
	}
	final_width, final_height := images.FitImage(self.src.size.Width, self.src.size.Height, width, height)
	if final_width == self.src.size.Width && final_height == self.src.data.Height {
		self.renderings[sz] = self.src.data
		return
	}
	x_frac, y_frac := float64(final_width)/float64(self.src.size.Width), float64(final_height)/float64(self.src.size.Height)
	self.renderings[sz] = self.src.data.Resize(x_frac, y_frac)
}

func (self *ImageCollection) ResizeForPageSize(width, height int) {
	self.mutex.Lock()
	defer self.mutex.Unlock()

	ctx := images.Context{}
	keys := maps.Keys(self.images)
	ctx.Parallel(0, len(keys), func(nums <-chan int) {
		for i := range nums {
			img := self.images[keys[i]]
			img.ResizeForPageSize(width, height)
		}
	})
}

func (self *ImageCollection) DeleteAllPlacements(lp *loop.Loop) {
	g := &GraphicsCommand{}
	g.SetAction(GRT_action_delete).SetDelete(GRT_delete_visible)
	g.WriteWithPayloadToLoop(lp, nil)
}

func (self *ImageCollection) LoadAll() {
	self.mutex.Lock()
	defer self.mutex.Unlock()
	ctx := images.Context{}
	all := maps.Values(self.images)
	ctx.Parallel(0, len(self.images), func(nums <-chan int) {
		for i := range nums {
			img := all[i]
			if !img.src.loaded {
				img.src.data, img.err = images.OpenImageFromPath(img.src.path)
				if img.err == nil {
					img.src.size.Width, img.src.size.Height = img.src.data.Width, img.src.data.Height
				}
			}
		}
	})
}

func NewImageCollection(paths ...string) *ImageCollection {
	items := make(map[string]*Image, len(paths))
	for _, path := range paths {
		i := &Image{}
		i.src.path = path
		items[path] = i
	}
	return &ImageCollection{images: items}
}
