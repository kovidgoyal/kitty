// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"fmt"
	"image"
	"kitty/tools/tui/graphics"
	"kitty/tools/utils/images"
	"kitty/tools/utils/shm"

	"github.com/disintegration/imaging"
)

var _ = fmt.Print

func add_frame(imgd *image_data, img image.Image, is_opaque bool) {
	if flip {
		img = imaging.FlipV(img)
	}
	if flop {
		img = imaging.FlipH(img)
	}
	b := img.Bounds()
	f := image_frame{width: b.Dx(), height: b.Dy()}
	dest_rect := image.Rect(0, 0, f.width, f.height)
	var final_img image.Image

	if is_opaque || remove_alpha != nil {
		var rgb *images.NRGB
		m, err := shm.CreateTemp("icat-*", uint64(f.width*f.height*3))
		if err != nil {
			rgb = images.NewNRGB(dest_rect)
		} else {
			rgb = &images.NRGB{Pix: m.Slice(), Stride: 3 * f.width, Rect: dest_rect}
			f.shm = m
		}
		f.transmission_format = graphics.GRT_format_rgb
		f.in_memory_bytes = rgb.Pix
		final_img = rgb
	} else {
		var rgba *image.NRGBA
		m, err := shm.CreateTemp("icat-*", uint64(f.width*f.height*4))
		if err != nil {
			rgba = image.NewNRGBA(dest_rect)
		} else {
			rgba = &image.NRGBA{Pix: m.Slice(), Stride: 4 * f.width, Rect: dest_rect}
			f.shm = m
		}
		f.transmission_format = graphics.GRT_format_rgba
		f.in_memory_bytes = rgba.Pix
		final_img = rgba
	}
	images.PasteCenter(final_img, img, remove_alpha)
	imgd.frames = append(imgd.frames, &f)
}

func load_one_frame_image(imgd *image_data, src *opened_input) (img image.Image, is_opaque bool, err error) {
	img, err = imaging.Decode(src.file, imaging.AutoOrientation(true))
	src.Rewind()
	if err != nil {
		return
	}
	// reset the sizes as we read EXIF tags here which could have rotated the image
	imgd.canvas_width = img.Bounds().Dx()
	imgd.canvas_height = img.Bounds().Dy()
	set_basic_metadata(imgd)
	is_opaque = images.IsOpaque(img)
	if imgd.needs_scaling {
		if imgd.canvas_width < imgd.available_width && opts.ScaleUp && place != nil {
			r := float64(imgd.available_width) / float64(imgd.canvas_width)
			imgd.canvas_width, imgd.canvas_height = imgd.available_width, int(r*float64(imgd.canvas_height))
		}
		imgd.canvas_width, imgd.canvas_height = images.FitImage(imgd.canvas_width, imgd.canvas_height, imgd.available_width, imgd.available_height)
		img = imaging.Resize(img, imgd.canvas_width, imgd.canvas_height, imaging.Lanczos)
		imgd.needs_scaling = false
	}
	return
}

func render_image_with_go(imgd *image_data, src *opened_input) (err error) {
	switch imgd.format_uppercase {
	case "GIF":
		return fmt.Errorf("TODO: implement GIF decoding")
	default:
		img, is_opaque, err := load_one_frame_image(imgd, src)
		if err != nil {
			return err
		}
		add_frame(imgd, img, is_opaque)
	}
	return nil
}
