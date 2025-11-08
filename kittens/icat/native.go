// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"fmt"
	"image"

	"github.com/kovidgoyal/go-parallel"
	"github.com/kovidgoyal/imaging/nrgb"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"github.com/kovidgoyal/kitty/tools/utils/shm"

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

func add_frame(ctx *images.Context, imgd *image_data, img image.Image, left, top int) *image_frame {
	is_opaque := imaging.IsOpaque(img)
	b := img.Bounds()
	if imgd.scaled_frac.x != 0 {
		img, b = resize_frame(imgd, img)
	}
	f := image_frame{width: b.Dx(), height: b.Dy(), number: len(imgd.frames) + 1, left: left, top: top}
	dest_rect := image.Rect(0, 0, f.width, f.height)
	var final_img image.Image
	bytes_per_pixel := 4

	if is_opaque || remove_alpha != nil {
		var rgb *imaging.NRGB
		bytes_per_pixel = 3
		m, err := shm.CreateTemp(shm_template, uint64(f.width*f.height*bytes_per_pixel))
		if err != nil {
			rgb = nrgb.NewNRGB(dest_rect)
		} else {
			rgb = &imaging.NRGB{Pix: m.Slice(), Stride: bytes_per_pixel * f.width, Rect: dest_rect}
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

func scale_up(width, height, maxWidth, maxHeight int) (newWidth, newHeight int) {
	if width == 0 || height == 0 {
		return 0, 0
	}

	// Calculate the ratio to scale the width and the ratio to scale the height.
	// We use floating-point division for precision.
	widthRatio := float64(maxWidth) / float64(width)
	heightRatio := float64(maxHeight) / float64(height)

	// To preserve the aspect ratio and fit within the limits, we must use the
	// smaller of the two scaling ratios.
	var ratio float64
	if widthRatio < heightRatio {
		ratio = widthRatio
	} else {
		ratio = heightRatio
	}

	// Calculate the new dimensions and convert them back to uints.
	newWidth = int(float64(width) * ratio)
	newHeight = int(float64(height) * ratio)

	return newWidth, newHeight
}

func scale_image(imgd *image_data) bool {
	if imgd.needs_scaling {
		width, height := imgd.canvas_width, imgd.canvas_height
		if opts.ScaleUp && (imgd.canvas_width < imgd.available_width || imgd.canvas_height < imgd.available_height) && (imgd.available_height != inf || imgd.available_width != inf) {
			imgd.canvas_width, imgd.canvas_height = scale_up(imgd.canvas_width, imgd.canvas_height, imgd.available_width, imgd.available_height)
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

var debugprintln = tty.DebugPrintln
var _ = debugprintln

func add_frames(ctx *images.Context, imgd *image_data, gf *imaging.Image) {
	for _, f := range gf.Frames {
		frame := add_frame(ctx, imgd, f.Image, f.TopLeft.X, f.TopLeft.Y)
		frame.number, frame.compose_onto = int(f.Number), int(f.ComposeOnto)
		frame.replace = f.Replace
		frame.delay_ms = int(f.Delay.Milliseconds())
		if frame.delay_ms <= 0 {
			frame.delay_ms = -1 // -1 is gapless in graphics protocol
		}
	}
}

func render_image_with_go(imgd *image_data, src *opened_input) (err error) {
	defer func() {
		if r := recover(); r != nil {
			err = parallel.Format_stacktrace_on_panic(r, 1)
		}
	}()
	ctx := images.Context{}
	imgs, _, err := imaging.DecodeAll(src.file)
	if err != nil {
		return err
	}
	if imgs == nil {
		return fmt.Errorf("unknown image format")
	}
	imgd.format_uppercase = imgs.Metadata.Format.String()
	// Loading could auto orient and therefore change width/height, so
	// re-calculate
	b := imgs.Bounds()
	imgd.canvas_width, imgd.canvas_height = b.Dx(), b.Dy()
	set_basic_metadata(imgd)
	scale_image(imgd)
	add_frames(&ctx, imgd, imgs)
	return nil
}
