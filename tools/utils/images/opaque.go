// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"image"
)

var _ = fmt.Print

func IsOpaque(img image.Image) bool {
	switch img.(type) {
	case *image.RGBA:
		return img.(*image.RGBA).Opaque()
	case *image.RGBA64:
		return img.(*image.RGBA64).Opaque()
	case *image.NRGBA:
		return img.(*image.NRGBA).Opaque()
	case *image.NRGBA64:
		return img.(*image.NRGBA).Opaque()
	case *image.Alpha:
		return img.(*image.Alpha).Opaque()
	case *image.Alpha16:
		return img.(*image.Alpha16).Opaque()
	case *image.Gray:
		return img.(*image.Gray).Opaque()
	case *image.Gray16:
		return img.(*image.Gray16).Opaque()
	case *image.CMYK:
		return img.(*image.CMYK).Opaque()
	case *image.Paletted:
		return img.(*image.Paletted).Opaque()
	case *image.Uniform:
		return img.(*image.Uniform).Opaque()
	case *image.YCbCr:
		return img.(*image.YCbCr).Opaque()
	case *NRGB:
		return img.(*NRGB).Opaque()
	}
	return false
}
