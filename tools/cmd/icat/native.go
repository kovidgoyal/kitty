// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"fmt"
	"image"
	"image/gif"
	"kitty/tools/tui/graphics"
	"kitty/tools/utils"
	"kitty/tools/utils/images"
	"kitty/tools/utils/shm"

	"github.com/disintegration/imaging"
)

var _ = fmt.Print

func add_frame(imgd *image_data, img image.Image, is_opaque bool) *image_frame {
	if flip {
		img = imaging.FlipV(img)
	}
	if flop {
		img = imaging.FlipH(img)
	}
	b := img.Bounds()
	f := image_frame{width: b.Dx(), height: b.Dy(), number: len(imgd.frames), left: b.Min.X, top: b.Min.Y}
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
	return &f
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

func add_gif_frames(imgd *image_data, gf *gif.GIF) error {
	max_gap := utils.Max(0, gf.Delay...)
	min_gap := 0
	if max_gap <= 0 {
		min_gap = 1
	}

	min_gap *= 1
	anchor_frame := 1
	for i, img := range gf.Image {
		frame := add_frame(imgd, img, img.Opaque())
		frame.delay_ms = utils.Max(min_gap, gf.Delay[i]) * 10
		if frame.delay_ms == 0 {
			frame.delay_ms = -1
		}
		if i > 0 {
			switch gf.Disposal[i] {
			case gif.DisposalNone:
				frame.compose_onto = frame.number - 1
				anchor_frame = frame.number
			case gif.DisposalBackground:
				// see https://github.com/golang/go/issues/20694
				anchor_frame = frame.number
			case gif.DisposalPrevious:
				frame.compose_onto = anchor_frame
			}
		}
	}
	return nil
}

func render_image_with_go(imgd *image_data, src *opened_input) (err error) {
	switch {
	case imgd.format_uppercase == "GIF" && opts.Loop != 0:
		gif_frames, err := gif.DecodeAll(src.file)
		src.Rewind()
		if err != nil {
			return fmt.Errorf("Failed to decode GIF file with error: %w", err)
		}
		err = add_gif_frames(imgd, gif_frames)
		if err != nil {
			return err
		}
	default:
		img, is_opaque, err := load_one_frame_image(imgd, src)
		if err != nil {
			return err
		}
		add_frame(imgd, img, is_opaque)
	}
	return nil
}
