// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"fmt"

	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/utils/images"
)

var _ = fmt.Print

func Render(path string, ro *images.RenderOptions, frames []images.IdentifyRecord) (ans []*image_frame, err error) {
	ro.TempfilenameTemplate = shm_template
	image_frames, filenames, err := images.RenderWithMagick(path, ro, frames)
	if err == nil {
		ans = make([]*image_frame, len(image_frames))
		for i, x := range image_frames {
			ans[i] = &image_frame{
				filename: filenames[x.Number], filename_is_temporary: true,
				number: x.Number, width: x.Width, height: x.Height, left: x.Left, top: x.Top,
				transmission_format: graphics.GRT_format_rgba, delay_ms: int(x.Delay_ms), compose_onto: x.Compose_onto,
			}
			if x.Is_opaque {
				ans[i].transmission_format = graphics.GRT_format_rgb
			}
		}
	}
	return ans, err
}

func render_image_with_magick(imgd *image_data, src *opened_input) (err error) {
	err = src.PutOnFilesystem()
	if err != nil {
		return err
	}
	frames, err := images.IdentifyWithMagick(src.FileSystemName())
	if err != nil {
		return err
	}
	imgd.format_uppercase = frames[0].Fmt_uppercase
	imgd.canvas_width, imgd.canvas_height = frames[0].Canvas.Width, frames[0].Canvas.Height
	set_basic_metadata(imgd)
	if !imgd.needs_conversion {
		make_output_from_input(imgd, src)
		return nil
	}
	ro := images.RenderOptions{RemoveAlpha: remove_alpha, Flip: flip, Flop: flop}
	if scale_image(imgd) {
		ro.ResizeTo.X, ro.ResizeTo.Y = imgd.canvas_width, imgd.canvas_height
	}
	imgd.frames, err = Render(src.FileSystemName(), &ro, frames)
	if err != nil {
		return err
	}
	return nil
}
