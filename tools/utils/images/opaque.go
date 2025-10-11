// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"image"

	"github.com/kovidgoyal/imaging"
)

var _ = fmt.Print

func paletted_is_opaque(p *image.Paletted) bool {
	if len(p.Palette) > 256 {
		return p.Opaque()
	}
	var is_alpha [256]bool
	has_alpha := false
	for i, c := range p.Palette {
		_, _, _, a := c.RGBA()
		if a != 0xffff {
			is_alpha[i] = true
			has_alpha = true
		}
	}
	if !has_alpha {
		return true
	}
	i0, i1 := 0, p.Rect.Dx()
	for y := p.Rect.Min.Y; y < p.Rect.Max.Y; y++ {
		for _, c := range p.Pix[i0:i1] {
			if is_alpha[c] {
				return false
			}
		}
		i0 += p.Stride
		i1 += p.Stride
	}
	return true
}

func IsOpaque(img image.Image) bool {
	switch i := img.(type) {
	case *image.RGBA:
		return i.Opaque()
	case *image.RGBA64:
		return i.Opaque()
	case *image.NRGBA:
		return i.Opaque()
	case *image.NRGBA64:
		return i.Opaque()
	case *image.Alpha:
		return i.Opaque()
	case *image.Alpha16:
		return i.Opaque()
	case *image.Gray:
		return i.Opaque()
	case *image.Gray16:
		return i.Opaque()
	case *image.CMYK:
		return i.Opaque()
	case *image.Paletted:
		return paletted_is_opaque(i)
	case *image.Uniform:
		return i.Opaque()
	case *image.YCbCr:
		return i.Opaque()
	case *imaging.NRGB:
		return i.Opaque()
	}
	return false
}
