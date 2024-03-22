// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"image"
)

var _ = fmt.Print

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
		return i.Opaque()
	case *image.Uniform:
		return i.Opaque()
	case *image.YCbCr:
		return i.Opaque()
	case *NRGB:
		return i.Opaque()
	}
	return false
}
