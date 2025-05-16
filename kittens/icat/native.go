// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"github.com/kovidgoyal/kitty/tools/utils/shm"
	"image"
	"image/gif"

	"github.com/edwvee/exiffix"
	"github.com/kovidgoyal/imaging"
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

const shm_template = "kitty-icat-*"

func add_frame(ctx *images.Context, imgd *image_data, img image.Image) *image_frame {
	is_opaque := false
	if imgd.format_uppercase == "JPEG" {
		// special cased because EXIF orientation could have already changed this image to an NRGBA making IsOpaque() very slow
		is_opaque = true
	} else {
		is_opaque = images.IsOpaque(img)
	}
	b := img.Bounds()
	if imgd.scaled_frac.x != 0 {
		img, b = resize_frame(imgd, img)
	}
	f := image_frame{width: b.Dx(), height: b.Dy(), number: len(imgd.frames) + 1, left: b.Min.X, top: b.Min.Y}
	dest_rect := image.Rect(0, 0, f.width, f.height)
	var final_img image.Image
	bytes_per_pixel := 4

	if is_opaque || remove_alpha != nil {
		var rgb *images.NRGB
		bytes_per_pixel = 3
		m, err := shm.CreateTemp(shm_template, uint64(f.width*f.height*bytes_per_pixel))
		if err != nil {
			rgb = images.NewNRGB(dest_rect)
		} else {
			rgb = &images.NRGB{Pix: m.Slice(), Stride: bytes_per_pixel * f.width, Rect: dest_rect}
			f.shm = m
		}
		f.transmission_format = graphics.GRT_format_rgb
		f.in_memory_bytes = rgb.Pix
		final_img = rgb
	} else {
		var rgba *image.NRGBA
		m, err := shm.CreateTemp(shm_template, uint64(f.width*f.height*bytes_per_pixel))
		if err != nil {
			rgba = image.NewNRGBA(dest_rect)
		} else {
			rgba = &image.NRGBA{Pix: m.Slice(), Stride: bytes_per_pixel * f.width, Rect: dest_rect}
			f.shm = m
		}
		f.transmission_format = graphics.GRT_format_rgba
		f.in_memory_bytes = rgba.Pix
		final_img = rgba
	}
	ctx.PasteCenter(final_img, img, remove_alpha)
	imgd.frames = append(imgd.frames, &f)
	if flip {
		ctx.FlipPixelsV(bytes_per_pixel, f.width, f.height, f.in_memory_bytes)
		if f.height < imgd.canvas_height {
			f.top = (2*imgd.canvas_height - f.height - f.top) % imgd.canvas_height
		}
	}
	if flop {
		ctx.FlipPixelsH(bytes_per_pixel, f.width, f.height, f.in_memory_bytes)
		if f.width < imgd.canvas_width {
			f.left = (2*imgd.canvas_width - f.width - f.left) % imgd.canvas_width
		}
	}
	return &f
}

func scale_image(imgd *image_data) bool {
	if imgd.needs_scaling {
		width, height := imgd.canvas_width, imgd.canvas_height
		if imgd.canvas_width < imgd.available_width && opts.ScaleUp && place != nil {
			r := float64(imgd.available_width) / float64(imgd.canvas_width)
			imgd.canvas_width, imgd.canvas_height = imgd.available_width, int(r*float64(imgd.canvas_height))
		}
		neww, newh := images.FitImage(imgd.canvas_width, imgd.canvas_height, imgd.available_width, imgd.available_height)
		imgd.needs_scaling = false
		imgd.scaled_frac.x = float64(neww) / float64(width)
		imgd.scaled_frac.y = float64(newh) / float64(height)
		imgd.canvas_width = int(imgd.scaled_frac.x * float64(width))
		imgd.canvas_height = int(imgd.scaled_frac.y * float64(height))
		return true
	}
	return false
}

func load_one_frame_image(imgd *image_data, src *opened_input) (img image.Image, err error) {
	img, _, err = exiffix.Decode(src.file)
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

var debugprintln = tty.DebugPrintln
var _ = debugprintln

func (frame *image_frame) set_disposal(anchor_frame int, disposal byte) int {
	anchor_frame, frame.compose_onto = images.SetGIFFrameDisposal(frame.number, anchor_frame, disposal)
	return anchor_frame
}

func (frame *image_frame) set_delay(gap, min_gap int) {
	frame.delay_ms = utils.Max(min_gap, gap) * 10
	if frame.delay_ms == 0 {
		frame.delay_ms = -1
	}
}

func add_gif_frames(ctx *images.Context, imgd *image_data, gf *gif.GIF) error {
	min_gap := images.CalcMinimumGIFGap(gf.Delay)
	scale_image(imgd)
	anchor_frame := 1
	for i, paletted_img := range gf.Image {
		frame := add_frame(ctx, imgd, paletted_img)
		frame.set_delay(gf.Delay[i], min_gap)
		anchor_frame = frame.set_disposal(anchor_frame, gf.Disposal[i])
	}
	return nil
}

func render_image_with_go(imgd *image_data, src *opened_input) (err error) {
	ctx := images.Context{}
	switch {
	case imgd.format_uppercase == "GIF" && opts.Loop != 0:
		gif_frames, err := gif.DecodeAll(src.file)
		src.Rewind()
		if err != nil {
			return fmt.Errorf("Failed to decode GIF file with error: %w", err)
		}
		err = add_gif_frames(&ctx, imgd, gif_frames)
		if err != nil {
			return err
		}
	default:
		img, err := load_one_frame_image(imgd, src)
		if err != nil {
			return err
		}
		add_frame(&ctx, imgd, img)
	}
	return nil
}
