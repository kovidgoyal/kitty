// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package graphics

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"sync"
	"sync/atomic"

	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"github.com/kovidgoyal/kitty/tools/utils/shm"
)

var _ = fmt.Print

type Size struct{ Width, Height int }

type rendering struct {
	img      *images.ImageData
	image_id uint32
}

type temp_resource struct {
	path string
	mmap shm.MMap
}

func (self *temp_resource) remove() {
	if self.path != "" {
		os.Remove(self.path)
		self.path = ""
	}
	if self.mmap != nil {
		_ = self.mmap.Unlink()
		self.mmap = nil
	}
}

type Image struct {
	src struct {
		path   string
		data   *images.ImageData
		size   Size
		loaded bool
	}
	renderings map[Size]*rendering
	err        error
}

func NewImage() *Image {
	return &Image{
		renderings: make(map[Size]*rendering),
	}
}

type ImageCollection struct {
	Shm_supported, Files_supported      atomic.Bool
	detection_file_id, detection_shm_id uint32
	temp_file_map                       map[uint32]*temp_resource
	running_in_tmux                     bool

	mutex            sync.Mutex
	image_id_counter uint32

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
		if img.err != nil {
			return Size{}, img.err
		}
		return Size{}, ErrNotFound
	}
	return Size{ans.img.Width, ans.img.Height}, img.err
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
			i := NewImage()
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
		self.renderings[sz] = &rendering{img: self.src.data}
		return
	}
	x_frac, y_frac := float64(final_width)/float64(self.src.size.Width), float64(final_height)/float64(self.src.size.Height)
	self.renderings[sz] = &rendering{img: self.src.data.Resize(x_frac, y_frac)}
}

func (self *ImageCollection) ResizeForPageSize(width, height int) {
	self.mutex.Lock()
	defer self.mutex.Unlock()

	ctx := images.Context{}
	keys := utils.Keys(self.images)
	ctx.Parallel(0, len(keys), func(nums <-chan int) {
		for i := range nums {
			img := self.images[keys[i]]
			if img.src.loaded && img.err == nil {
				img.ResizeForPageSize(width, height)
			}
		}
	})
}

func (self *ImageCollection) DeleteAllVisiblePlacements(lp *loop.Loop) {
	g := self.new_graphics_command()
	g.SetAction(GRT_action_delete).SetDelete(GRT_delete_visible)
	_ = g.WriteWithPayloadToLoop(lp, nil)
}

func (self *ImageCollection) PlaceImageSubRect(lp *loop.Loop, key string, page_size Size, left, top, width, height int) {
	self.mutex.Lock()
	defer self.mutex.Unlock()
	img := self.images[key]
	if img == nil {
		return
	}
	r := img.renderings[page_size]
	if r == nil {
		return
	}
	if r.image_id == 0 {
		self.transmit_rendering(lp, r)
	}
	if width < 0 {
		width = r.img.Width
	}
	if height < 0 {
		height = r.img.Height
	}
	width = utils.Max(0, utils.Min(r.img.Width-left, width))
	height = utils.Max(0, utils.Min(r.img.Height-top, height))
	gc := self.new_graphics_command()
	gc.SetAction(GRT_action_display).SetLeftEdge(uint64(left)).SetTopEdge(uint64(top)).SetWidth(uint64(width)).SetHeight(uint64(height))
	gc.SetImageId(r.image_id).SetPlacementId(1).SetCursorMovement(GRT_cursor_static)
	_ = gc.WriteWithPayloadToLoop(lp, nil)
}

func (self *ImageCollection) Initialize(lp *loop.Loop) {
	tmux := tui.TmuxSocketAddress()
	if tmux != "" && tui.TmuxAllowPassthrough() == nil {
		self.running_in_tmux = true
	}
	if !self.running_in_tmux {
		g := func(t GRT_t, payload string) uint32 {
			self.image_id_counter++
			g1 := self.new_graphics_command()
			g1.SetTransmission(t).SetAction(GRT_action_query).SetImageId(self.image_id_counter).SetDataWidth(1).SetDataHeight(1).SetFormat(
				GRT_format_rgb).SetDataSize(uint64(len(payload)))
			_ = g1.WriteWithPayloadToLoop(lp, utils.UnsafeStringToBytes(payload))
			return self.image_id_counter
		}
		tf, err := images.CreateTempInRAM()
		if err == nil {
			if _, err = tf.Write([]byte{1, 2, 3}); err == nil {
				self.detection_file_id = g(GRT_transmission_tempfile, tf.Name())
				self.temp_file_map[self.detection_file_id] = &temp_resource{path: tf.Name()}
			}
			tf.Close()
		}
		sf, err := shm.CreateTemp("icat-", 3)
		if err == nil {
			copy(sf.Slice(), []byte{1, 2, 3})
			sf.Close()
			self.detection_shm_id = g(GRT_transmission_sharedmem, sf.Name())
			self.temp_file_map[self.detection_shm_id] = &temp_resource{mmap: sf}
		}
	}
}

func (self *ImageCollection) Finalize(lp *loop.Loop) {
	for _, tr := range self.temp_file_map {
		tr.remove()
	}
	for _, img := range self.images {
		for _, r := range img.renderings {
			if r.image_id > 0 {
				g := self.new_graphics_command()
				g.SetAction(GRT_action_delete).SetDelete(GRT_free_by_id).SetImageId(r.image_id)
				_ = g.WriteWithPayloadToLoop(lp, nil)
			}
		}
		img.renderings = nil
	}
	self.images = nil
}

func (self *ImageCollection) mark_img_as_needing_transmission(id uint32) bool {
	self.mutex.Lock()
	defer self.mutex.Unlock()

	for _, img := range self.images {
		for _, r := range img.renderings {
			if r.image_id == id {
				r.image_id = 0
				return true
			}
		}
	}
	return false
}

// Handle graphics response. Returns false if an image needs re-transmission because
// the terminal replied with ENOENT for a placement
func (self *ImageCollection) HandleGraphicsCommand(gc *GraphicsCommand) bool {
	switch gc.ImageId() {
	case self.detection_file_id:
		if gc.ResponseMessage() == "OK" {
			self.Files_supported.Store(true)
		} else {
			if tr := self.temp_file_map[gc.ImageId()]; tr != nil {
				tr.remove()
			}
		}
		delete(self.temp_file_map, gc.ImageId())
		self.detection_file_id = 0
		return true
	case self.detection_shm_id:
		if gc.ResponseMessage() == "OK" {
			self.Shm_supported.Store(true)
		} else {
			if tr := self.temp_file_map[gc.ImageId()]; tr != nil {
				tr.remove()
			}
		}
		delete(self.temp_file_map, gc.ImageId())
		self.detection_shm_id = 0
		return true
	}
	if is_transmission_response := gc.PlacementId() == 0; is_transmission_response {
		if gc.ResponseMessage() != "OK" {
			// this should never happen but lets cleanup anyway
			if tr := self.temp_file_map[gc.ImageId()]; tr != nil {
				tr.remove()
				delete(self.temp_file_map, gc.ImageId())
			}
		}
		return true
	}
	if gc.ResponseMessage() != "OK" && gc.PlacementId() != 0 {
		if self.mark_img_as_needing_transmission(gc.ImageId()) {
			return false
		}
	}
	return true
}

func (self *ImageCollection) LoadAll() {
	self.mutex.Lock()
	defer self.mutex.Unlock()
	ctx := images.Context{}
	all := utils.Values(self.images)
	ctx.Parallel(0, len(self.images), func(nums <-chan int) {
		for i := range nums {
			img := all[i]
			if !img.src.loaded {
				img.src.data, img.err = images.OpenImageFromPath(img.src.path)
				if img.err == nil {
					img.src.size.Width, img.src.size.Height = img.src.data.Width, img.src.data.Height
				}
				img.src.loaded = true
			}
		}
	})
}

func NewImageCollection(paths ...string) *ImageCollection {
	items := make(map[string]*Image, len(paths))
	for _, path := range paths {
		i := NewImage()
		i.src.path = path
		items[path] = i
	}
	return &ImageCollection{images: items, temp_file_map: make(map[uint32]*temp_resource)}
}

func (self *ImageCollection) new_graphics_command() *GraphicsCommand {
	gc := GraphicsCommand{}
	if self.running_in_tmux {
		gc.WrapPrefix = "\033Ptmux;"
		gc.WrapSuffix = "\033\\"
		gc.EncodeSerializedDataFunc = func(x string) string { return strings.ReplaceAll(x, "\033", "\033\033") }
	}
	return &gc
}

func transmit_by_escape_code(lp *loop.Loop, image_id uint32, temp_file_map map[uint32]*temp_resource, frame *images.ImageFrame, gc *GraphicsCommand) {
	atomic := lp.IsAtomicUpdateActive()
	lp.EndAtomicUpdate()
	gc.SetTransmission(GRT_transmission_direct)
	_ = gc.WriteWithPayloadToLoop(lp, frame.Data())
	if atomic {
		lp.StartAtomicUpdate()
	}
}

func transmit_by_shm(lp *loop.Loop, image_id uint32, temp_file_map map[uint32]*temp_resource, frame *images.ImageFrame, gc *GraphicsCommand) {
	mmap, err := frame.DataAsSHM("kdiff-img-*")
	if err != nil {
		transmit_by_escape_code(lp, image_id, temp_file_map, frame, gc)
		return
	}
	mmap.Close()
	temp_file_map[image_id] = &temp_resource{mmap: mmap}
	gc.SetTransmission(GRT_transmission_sharedmem)
	_ = gc.WriteWithPayloadToLoop(lp, utils.UnsafeStringToBytes(mmap.Name()))
}

func transmit_by_file(lp *loop.Loop, image_id uint32, temp_file_map map[uint32]*temp_resource, frame *images.ImageFrame, gc *GraphicsCommand) {
	f, err := images.CreateTempInRAM()
	if err != nil {
		transmit_by_escape_code(lp, image_id, temp_file_map, frame, gc)
		return
	}
	defer f.Close()
	temp_file_map[image_id] = &temp_resource{path: f.Name()}
	_, err = f.Write(frame.Data())
	if err != nil {
		transmit_by_escape_code(lp, image_id, temp_file_map, frame, gc)
		return
	}
	gc.SetTransmission(GRT_transmission_tempfile)
	_ = gc.WriteWithPayloadToLoop(lp, utils.UnsafeStringToBytes(f.Name()))
}

func (self *ImageCollection) transmit_rendering(lp *loop.Loop, r *rendering) {
	if r.image_id == 0 {
		self.image_id_counter++
		r.image_id = self.image_id_counter
	}
	is_animated := len(r.img.Frames) > 0
	transmit := transmit_by_escape_code
	if self.Shm_supported.Load() {
		transmit = transmit_by_shm
	} else if self.Files_supported.Load() {
		transmit = transmit_by_file
	}

	frame_control_cmd := self.new_graphics_command()
	frame_control_cmd.SetAction(GRT_action_animate).SetImageId(r.image_id)
	for frame_num, frame := range r.img.Frames {
		gc := self.new_graphics_command()
		gc.SetImageId(r.image_id)
		gc.SetDataWidth(uint64(frame.Width)).SetDataHeight(uint64(frame.Height))
		if frame.Is_opaque {
			gc.SetFormat(GRT_format_rgb)
		}
		switch frame_num {
		case 0:
			gc.SetAction(GRT_action_transmit)
			gc.SetCursorMovement(GRT_cursor_static)
		default:
			gc.SetAction(GRT_action_frame)
			gc.SetGap(frame.Delay_ms)
			if frame.Compose_onto > 0 {
				gc.SetOverlaidFrame(uint64(frame.Compose_onto))
			}
			gc.SetLeftEdge(uint64(frame.Left)).SetTopEdge(uint64(frame.Top))
		}
		transmit(lp, r.image_id, self.temp_file_map, frame, gc)
		if is_animated {
			switch frame_num {
			case 0:
				// set gap for the first frame and number of loops for the animation
				c := frame_control_cmd
				c.SetTargetFrame(uint64(frame.Number))
				c.SetGap(int32(frame.Delay_ms))
				c.SetNumberOfLoops(1)
				_ = c.WriteWithPayloadToLoop(lp, nil)
			case 1:
				c := frame_control_cmd
				c.SetAnimationControl(2) // set animation to loading mode
				_ = c.WriteWithPayloadToLoop(lp, nil)
			}
		}
	}
	if is_animated {
		c := frame_control_cmd
		c.SetAnimationControl(3) // set animation to normal mode
		_ = c.WriteWithPayloadToLoop(lp, nil)
	}
}
