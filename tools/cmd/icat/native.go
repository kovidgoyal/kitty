// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"fmt"
	"image"
	"kitty/tools/utils"
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
	has_non_black_background := remove_alpha != nil && (remove_alpha.R != 0 || remove_alpha.G != 0 || remove_alpha.B != 0)
	var rgba *image.NRGBA
	m, err := shm.CreateTemp("icat-*", uint64(f.width*f.height*4))
	if err != nil {
		if has_non_black_background {
			rgba = imaging.New(b.Dx(), b.Dy(), remove_alpha)
		} else {
			rgba = image.NewNRGBA(image.Rect(0, 0, f.width, f.height))
		}
	} else {
		rgba = &image.NRGBA{
			Pix:    m.Slice(),
			Stride: 4 * f.width,
			Rect:   image.Rect(0, 0, f.width, f.height),
		}
		f.shm = m
		if has_non_black_background {
			utils.Memset(m.Slice(), remove_alpha.R, remove_alpha.G, remove_alpha.B, remove_alpha.A)
		} else {
			utils.Memset(m.Slice())
		}
	}
	imaging.PasteCenter(rgba, img)
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
