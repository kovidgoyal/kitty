// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package graphics

import (
	"fmt"
	"image"
	"sync"
	"sync/atomic"

	"kitty/tools/utils/images"

	"golang.org/x/exp/maps"
)

var _ = fmt.Print

type Image struct {
	src struct {
		path   string
		data   *images.ImageData
		size   image.Point
		loaded bool
	}
	renderings map[image.Point]*images.ImageData
	err        error
}

type ImageCollection struct {
	Shm_supported, Files_supported atomic.Bool
	mutex                          sync.Mutex

	images map[string]*Image
}

func (self *ImageCollection) ResolutionOf(key string) image.Point {
	if !self.mutex.TryLock() {
		return image.Point{-1, -1}
	}
	defer self.mutex.Unlock()
	i := self.images[key]
	if i == nil {
		return image.Point{-2, -2}
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
					img.src.size.X, img.src.size.Y = img.src.data.Width, img.src.data.Height
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
