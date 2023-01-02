// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"fmt"
	"image"
	"kitty/tools/utils/images"
	"kitty/tools/utils/shm"

	"github.com/disintegration/imaging"
)

var _ = fmt.Print

func add_frame(imgd *image_data, img image.Image) {
	if flip {
		img = imaging.FlipV(img)
	}
	if flop {
		img = imaging.FlipH(img)
	}
	b := img.Bounds()
	f := image_frame{width: b.Dx(), height: b.Dy()}
	dest_rect := image.Rect(0, 0, f.width, f.height)
	var rgba *image.NRGBA
	m, err := shm.CreateTemp("icat-*", uint64(f.width*f.height*4))
	if err != nil {
		rgba = image.NewNRGBA(dest_rect)
	} else {
		rgba = &image.NRGBA{
			Pix:    m.Slice(),
			Stride: 4 * f.width,
			Rect:   dest_rect,
		}
		f.shm = m
	}
	images.PasteCenter(rgba, img, remove_alpha)
	imgd.format_uppercase = "RGBA"
	f.in_memory_bytes = rgba.Pix
	imgd.frames = append(imgd.frames, &f)
}

func load_one_frame_image(imgd *image_data, src *opened_input) (image.Image, error) {
	img, err := imaging.Decode(src.file, imaging.AutoOrientation(true))
	src.Rewind()
	if err == nil {
		// reset the sizes as we read EXIF tags here which could have rotated the image
		imgd.canvas_width = img.Bounds().Dx()
		imgd.canvas_height = img.Bounds().Dy()
		set_basic_metadata(imgd)
	}
	return img, err
}

func render_image_with_go(imgd *image_data, src *opened_input) (err error) {
	switch imgd.format_uppercase {
	case "GIF":
		return fmt.Errorf("TODO: implement GIF decoding")
	default:
		img, err := load_one_frame_image(imgd, src)
		if err != nil {
			return err
		}
		add_frame(imgd, img)
	}
	return nil
}
