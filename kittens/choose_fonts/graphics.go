package choose_fonts

import (
	"fmt"
	"strings"

	"kitty/tools/tui/graphics"
	"kitty/tools/tui/loop"
)

var _ = fmt.Print

type image struct {
	id, image_number uint32
	placement_id     uint32
	current_file     string
}

func (i image) graphics_command() *graphics.GraphicsCommand {
	gc := &graphics.GraphicsCommand{}
	if i.id > 0 {
		gc.SetImageId(i.id)
	} else {
		gc.SetImageNumber(i.image_number)
	}
	return gc
}

type graphics_manager struct {
	main, bold, italic, bi, extra image
	lp                            *loop.Loop
	images                        [5]*image
}

func (g *graphics_manager) initialize(lp *loop.Loop) {
	g.images = [5]*image{&g.main, &g.bold, &g.italic, &g.bi, &g.extra}
	g.lp = lp
	payload := []byte("123")
	buf := strings.Builder{}
	gc := &graphics.GraphicsCommand{}
	gc.SetImageNumber(7891230).SetTransmission(graphics.GRT_transmission_direct).SetDataWidth(1).SetDataHeight(1).SetFormat(
		graphics.GRT_format_rgb).SetDataSize(uint64(len(payload)))
	d := func() uint32 {
		im := gc.ImageNumber()
		im++
		gc.SetImageNumber(im)
		_ = gc.WriteWithPayloadTo(&buf, payload)
		return im

	}
	for _, img := range g.images {
		img.image_number = d()
	}
	lp.QueueWriteString(buf.String())
}

func (g *graphics_manager) clear_placements() {
	gc := graphics.GraphicsCommand{}
	gc.SetAction(graphics.GRT_action_delete).SetDelete(graphics.GRT_delete_visible)
	gc.WriteWithPayloadToLoop(g.lp, nil)
}

func (g *graphics_manager) display_image(slot int, path string, img_width, img_height int) {
	img := g.images[slot]
	if img.current_file != path {
		gc := img.graphics_command()
		gc.SetAction(graphics.GRT_action_transmit).SetFormat(graphics.GRT_format_rgba).SetDataWidth(uint64(img_width)).SetDataHeight(uint64(img_height)).SetTransmission(graphics.GRT_transmission_file)
		gc.WriteWithPayloadToLoop(g.lp, []byte(path))
	}
	gc := img.graphics_command()
	gc.SetAction(graphics.GRT_action_display).SetCursorMovement(graphics.GRT_cursor_static)
	gc.WriteWithPayloadToLoop(g.lp, nil)
}

func (g *graphics_manager) on_response(gc *graphics.GraphicsCommand) (err error) {
	if gc.ResponseMessage() != "OK" {
		return fmt.Errorf("Failed to load image with error: %s", gc.ResponseMessage())
	}
	for _, img := range g.images {
		if img.image_number == gc.ImageNumber() {
			img.id = gc.ImageId()
			break
		}
	}
	return
}

func (g *graphics_manager) finalize() {
	buf := strings.Builder{}
	gc := &graphics.GraphicsCommand{}
	gc.SetAction(graphics.GRT_action_delete).SetDelete(graphics.GRT_free_by_number)
	d := func(n uint32) {
		gc.SetImageNumber(n)
		gc.WriteWithPayloadTo(&buf, nil)
	}
	d(g.main.image_number)
	d(g.bold.image_number)
	d(g.italic.image_number)
	d(g.bi.image_number)
	d(g.extra.image_number)
	g.lp.QueueWriteString(buf.String())
}
