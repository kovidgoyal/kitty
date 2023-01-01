// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"fmt"
	"image"

	"golang.org/x/image/draw"
)

var _ = fmt.Print

func render_image_with_go(imgd *image_data, src *opened_input) (err error) {
	switch imgd.format_uppercase {
	case "GIF":
		return fmt.Errorf("TODO: implement GIF decoding")
	default:
		img, _, err := image.Decode(src.file)
		if err != nil {
			return err
		}
		b := img.Bounds()
		rgba := image.NewNRGBA(image.Rect(0, 0, b.Dx(), b.Dy()))
		draw.Draw(rgba, rgba.Bounds(), img, b.Min, draw.Src)
		imgd.format_uppercase = "RGBA"
		f := image_frame{width: b.Dx(), height: b.Dy()}
		f.in_memory_bytes = rgba.Pix
		imgd.frames = append(imgd.frames, &f)
	}
	return nil
}
