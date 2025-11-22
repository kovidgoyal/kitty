package choose_files

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"

	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
)

var _ = fmt.Print

type placement struct {
	gc             *graphics.GraphicsCommand
	x, y, x_offset int
}

func (p placement) equal(o placement) bool {
	return p.x == o.x && p.x_offset == o.x_offset && p.y == o.y
}

type GraphicsHandler struct {
	running_in_tmux                     bool
	image_id_counter, detection_file_id uint32
	files_to_delete                     []string
	files_supported                     atomic.Bool
	last_rendered_image                 struct {
		p                         *ImagePreview
		width, height             int
		image_width, image_height int
	}
	image_transmitted                             uint32
	current_placement, last_transmitted_placement placement
}

func (self *GraphicsHandler) Cleanup() {
	for _, f := range self.files_to_delete {
		_ = os.Remove(f)
	}
}

func (self *GraphicsHandler) new_graphics_command() *graphics.GraphicsCommand {
	gc := graphics.GraphicsCommand{}
	if self.running_in_tmux {
		gc.WrapPrefix = "\033Ptmux;"
		gc.WrapSuffix = "\033\\"
		gc.EncodeSerializedDataFunc = func(x string) string { return strings.ReplaceAll(x, "\033", "\033\033") }
	}
	return &gc
}

func (self *GraphicsHandler) Initialize(lp *loop.Loop) error {
	tmux := tui.TmuxSocketAddress()
	if tmux != "" && tui.TmuxAllowPassthrough() == nil {
		self.running_in_tmux = true
	}
	if !self.running_in_tmux {
		g := func(t graphics.GRT_t, payload string) uint32 {
			self.image_id_counter++
			g1 := self.new_graphics_command()
			g1.SetTransmission(t).SetAction(graphics.GRT_action_query).SetImageId(self.image_id_counter).SetDataWidth(1).SetDataHeight(1).SetFormat(
				graphics.GRT_format_rgb).SetDataSize(uint64(len(payload)))
			_ = g1.WriteWithPayloadToLoop(lp, utils.UnsafeStringToBytes(payload))
			return self.image_id_counter
		}
		tf, err := images.CreateTempInRAM()
		if err == nil {
			if _, err = tf.Write([]byte{1, 2, 3}); err == nil {
				self.detection_file_id = g(graphics.GRT_transmission_tempfile, tf.Name())
				self.files_to_delete = append(self.files_to_delete, tf.Name())
			}
			tf.Close()
		}

	}
	self.image_id_counter++
	return nil
}

func (self *GraphicsHandler) free_image_from_terminal(lp *loop.Loop) {
	if self.image_transmitted > 0 {
		self.new_graphics_command().SetAction(graphics.GRT_action_delete).SetDelete(graphics.GRT_free_by_id).SetImageId(self.image_transmitted).WriteWithPayloadToLoop(lp, nil)
		self.image_transmitted = 0
	}
}

func (self *GraphicsHandler) Finalize(lp *loop.Loop) {
	self.free_image_from_terminal(lp)
}

func (self *GraphicsHandler) ClearPlacements(lp *loop.Loop) {
	self.current_placement.gc = nil
}

func (self *GraphicsHandler) ApplyPlacements(lp *loop.Loop) {
	if self.current_placement.gc == nil {
		g := self.new_graphics_command()
		g.SetAction(graphics.GRT_action_delete).SetDelete(graphics.GRT_delete_by_id).SetImageId(self.image_transmitted)
		_ = g.WriteWithPayloadToLoop(lp, nil)
		self.last_transmitted_placement.gc = nil
	} else {
		if self.last_transmitted_placement.gc == nil || !self.current_placement.equal(self.last_transmitted_placement) {
			lp.MoveCursorTo(self.current_placement.x, self.current_placement.y)
			_ = self.current_placement.gc.WriteWithPayloadToLoop(lp, nil)
			self.last_transmitted_placement = self.current_placement
		}
	}
}

func (self *GraphicsHandler) HandleGraphicsCommand(gc *graphics.GraphicsCommand) error {
	switch gc.ImageId() {
	case self.detection_file_id:
		if gc.ResponseMessage() == "OK" {
			self.files_supported.Store(true)
		}
	}

	return nil
}

func (self *GraphicsHandler) cache_resized_image(cdir, cache_key string, img *images.ImageData) (m *images.SerializableImageMetadata, cached_data map[string]string, err error) {
	s, frames := img.Serialize()
	sd, err := json.Marshal(s)
	if err != nil {
		return nil, nil, err
	}
	path := filepath.Join(cdir, fmt.Sprintf("rsz-%s-metadata.json", cache_key))
	if err = os.WriteFile(path, sd, 0o600); err != nil {
		return nil, nil, fmt.Errorf("failed to write resized frame metadata to cache: %w", err)
	}
	cached_data = make(map[string]string, len(frames)+1)
	cached_data[IMAGE_METADATA_KEY] = path
	for i, f := range frames {
		path := filepath.Join(cdir, fmt.Sprintf("rsz-%s-%d", cache_key, i))
		key := IMAGE_DATA_PREFIX + strconv.Itoa(i)
		if err = os.WriteFile(path, f, 0o600); err != nil {
			return nil, nil, fmt.Errorf("failed to write resized frame %d data to cache: %w", i, err)
		}
		cached_data[key] = path
	}
	m = &s
	return
}

func (self *GraphicsHandler) cached_resized_image(cdir, cache_key string) (m *images.SerializableImageMetadata, cached_data map[string]string) {
	path := filepath.Join(cdir, fmt.Sprintf("rsz-%s-metadata.json", cache_key))
	b, err := os.ReadFile(path)
	if err != nil {
		return
	}
	var s images.SerializableImageMetadata
	if err = json.Unmarshal(b, &s); err != nil {
		return
	}
	m = &s
	cached_data = make(map[string]string, len(s.Frames)+1)
	cached_data[IMAGE_METADATA_KEY] = path
	for i := range len(s.Frames) {
		path := filepath.Join(cdir, fmt.Sprintf("rsz-%s-%d", cache_key, i))
		key := IMAGE_DATA_PREFIX + strconv.Itoa(i)
		cached_data[key] = path
	}
	return
}

func transmit_by_escape_code(lp *loop.Loop, frame []byte, gc *graphics.GraphicsCommand) {
	atomic := lp.IsAtomicUpdateActive()
	lp.EndAtomicUpdate()
	gc.SetTransmission(graphics.GRT_transmission_direct)
	_ = gc.WriteWithPayloadToLoop(lp, frame)
	if atomic {
		lp.StartAtomicUpdate()
	}
}

func transmit_by_file(lp *loop.Loop, frame_path []byte, gc *graphics.GraphicsCommand) {
	gc.SetTransmission(graphics.GRT_transmission_file)
	_ = gc.WriteWithPayloadToLoop(lp, frame_path)
}

func (self *GraphicsHandler) transmit(lp *loop.Loop, img *images.ImageData, m *images.SerializableImageMetadata, cached_data map[string]string) {
	if m == nil {
		s := img.SerializeOnlyMetadata()
		m = &s
	}
	self.image_transmitted = self.image_id_counter
	self.last_transmitted_placement.gc = nil
	self.last_rendered_image.image_width = m.Width
	self.last_rendered_image.image_height = m.Height
	is_animated := len(m.Frames) > 0
	frame_control_cmd := self.new_graphics_command()
	frame_control_cmd.SetAction(graphics.GRT_action_animate).SetImageId(self.image_transmitted)
	for frame_num, frame := range m.Frames {
		gc := self.new_graphics_command()
		gc.SetImageId(self.image_transmitted)
		gc.SetDataWidth(uint64(frame.Width)).SetDataHeight(uint64(frame.Height))
		gc.SetFormat(utils.IfElse(frame.Is_opaque, graphics.GRT_format_rgb, graphics.GRT_format_rgba))
		switch frame_num {
		case 0:
			gc.SetAction(graphics.GRT_action_transmit)
			gc.SetCursorMovement(graphics.GRT_cursor_static)
		default:
			gc.SetAction(graphics.GRT_action_frame)
			gc.SetGap(int32(frame.Delay_ms))
			if frame.Replace {
				gc.SetCompositionMode(graphics.Overwrite)
			}
			if frame.Compose_onto > 0 {
				gc.SetOverlaidFrame(uint64(frame.Compose_onto))
			}
			gc.SetLeftEdge(uint64(frame.Left)).SetTopEdge(uint64(frame.Top))
		}
		if cached_data == nil {
			_, _, _, data := img.Frames[frame_num].Data()
			transmit_by_escape_code(lp, data, gc)
		} else {
			path := cached_data[IMAGE_DATA_PREFIX+strconv.Itoa(frame_num)]
			transmit_by_file(lp, utils.UnsafeStringToBytes(path), gc)
		}
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

func (self *GraphicsHandler) place_image(x, y, px_width, y_offset int, sz ScreenSize) {
	gc := self.new_graphics_command()
	gc.SetAction(graphics.GRT_action_display).SetImageId(self.image_transmitted).SetPlacementId(1).SetCursorMovement(graphics.GRT_cursor_static)
	if extra := px_width - self.last_rendered_image.image_width; extra > 1 {
		extra /= 2
		x += extra / sz.cell_width
		self.current_placement.x_offset = extra % sz.cell_width
		gc.SetXOffset(uint64(self.current_placement.x_offset))
	}
	gc.SetYOffset(uint64(y_offset))
	self.current_placement.x, self.current_placement.y = x, y
	self.current_placement.gc = gc
}

func (self *GraphicsHandler) RenderImagePreview(h *Handler, p *ImagePreview, x, y, width, height int) {
	sz := h.screen_size
	px_width, px_height := width*sz.cell_width, height*sz.cell_height
	y_offset := sz.cell_height / 2
	px_height -= y_offset
	var err error
	defer func() {
		self.last_rendered_image.p = p
		self.last_rendered_image.width, self.last_rendered_image.height = width, height
		if err != nil {
			NewErrorPreview(fmt.Errorf("Failed to render image: %w", err)).Render(h, x, y, width, height)
		} else if self.image_transmitted > 0 {
			self.place_image(x, y, px_width, y_offset, sz)
		}
	}()
	if self.last_rendered_image.p == p && self.last_rendered_image.width == width && self.last_rendered_image.height == height {
		return
	}
	files_supported := self.files_supported.Load()

	if p.custom_metadata.image.Width <= px_width && p.custom_metadata.image.Height <= px_height {
		if files_supported {
			self.transmit(h.lp, nil, p.custom_metadata.image, p.cached_data)
		} else {
			if err = p.ensure_source_image(); err != nil {
				return
			}
			self.transmit(h.lp, p.source_img, p.custom_metadata.image, nil)
		}
		return
	}
	cache_key := fmt.Sprintf("%d-%d-%p", width, height, p)
	img_metadata, cached_data := self.cached_resized_image(p.disk_cache.ResultsDir(), cache_key)
	var img *images.ImageData
	if len(cached_data) == 0 {
		if err = p.ensure_source_image(); err != nil {
			return
		}
		img = p.source_img
		final_width, final_height := images.FitImage(img.Width, img.Height, px_width, px_height)
		if final_width != img.Width || final_height != img.Height {
			x_frac, y_frac := float64(final_width)/float64(img.Width), float64(final_height)/float64(img.Height)
			img = img.Resize(x_frac, y_frac)
		}
		if img_metadata, cached_data, err = self.cache_resized_image(p.disk_cache.ResultsDir(), cache_key, img); err != nil {
			err = fmt.Errorf("failed to cache resized image: %w", err)
			return
		}
	}
	if files_supported {
		self.transmit(h.lp, img, img_metadata, cached_data)
	} else {
		if img == nil {
			if img, err = load_image(cached_data); err != nil {
				err = fmt.Errorf("failed to load resized image from cache: %w", err)
				return
			}
		}
		self.transmit(h.lp, img, nil, nil)
	}
}
