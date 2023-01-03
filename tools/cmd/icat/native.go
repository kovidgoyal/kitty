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

func resize_frame(imgd *image_data, img image.Image) (image.Image, image.Rectangle) {
	b := img.Bounds()
	left, top, width, height := b.Min.X, b.Min.Y, b.Dx(), b.Dy()
	new_width := int(imgd.scaled_frac.x * float64(width))
	new_height := int(imgd.scaled_frac.y * float64(height))
	img = imaging.Resize(img, new_width, new_height, imaging.Lanczos)
	newleft := int(imgd.scaled_frac.x * float64(left))
	newtop := int(imgd.scaled_frac.y * float64(top))
	return img, image.Rect(newleft, newtop, newleft+new_width, newtop+new_height)
}

func add_frame(imgd *image_data, img image.Image) *image_frame {
	is_opaque := images.IsOpaque(img)
	b := img.Bounds()
	if imgd.scaled_frac.x != 0 {
		img, b = resize_frame(imgd, img)
	}
	if flip {
		img = imaging.FlipV(img)
	}
	if flop {
		img = imaging.FlipH(img)
	}
	f := image_frame{width: b.Dx(), height: b.Dy(), number: len(imgd.frames) + 1, left: b.Min.X, top: b.Min.Y}
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

func scale_image(imgd *image_data) {
	if imgd.needs_scaling {
		width, height := imgd.canvas_width, imgd.canvas_height
		if imgd.canvas_width < imgd.available_width && opts.ScaleUp && place != nil {
			r := float64(imgd.available_width) / float64(imgd.canvas_width)
			imgd.canvas_width, imgd.canvas_height = imgd.available_width, int(r*float64(imgd.canvas_height))
		}
		imgd.canvas_width, imgd.canvas_height = images.FitImage(imgd.canvas_width, imgd.canvas_height, imgd.available_width, imgd.available_height)
		imgd.needs_scaling = false
		imgd.scaled_frac.x = float64(imgd.canvas_width) / float64(width)
		imgd.scaled_frac.y = float64(imgd.canvas_height) / float64(height)
	}
}

func load_one_frame_image(imgd *image_data, src *opened_input) (img image.Image, err error) {
	img, err = imaging.Decode(src.file, imaging.AutoOrientation(true))
	src.Rewind()
	if err != nil {
		return
	}
	// reset the sizes as we read EXIF tags here which could have rotated the image
	imgd.canvas_width = img.Bounds().Dx()
	imgd.canvas_height = img.Bounds().Dy()
	set_basic_metadata(imgd)
	scale_image(imgd)
	return
}

func add_gif_frames(imgd *image_data, gf *gif.GIF) error {
	// Some broken GIF images have all zero gaps, browsers with their usual
	// idiot ideas render these with a default 100ms gap https://bugzilla.mozilla.org/show_bug.cgi?id=125137
	// Browsers actually force a 100ms gap at any zero gap frame, but that
	// just means it is impossible to deliberately use zero gap frames for
	// sophisticated blending, so we dont do that.
	max_gap := utils.Max(0, gf.Delay...)
	min_gap := 0
	if max_gap <= 0 {
		min_gap = 10
	}
	min_gap *= 1
	scale_image(imgd)
	anchor_frame := 1
	for i, paletted_img := range gf.Image {
		frame := add_frame(imgd, paletted_img)
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
		img, err := load_one_frame_image(imgd, src)
		if err != nil {
			return err
		}
		add_frame(imgd, img)
	}
	return nil
}
