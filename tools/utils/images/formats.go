// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"image"
	"image/gif"
	"image/jpeg"
	"image/png"
	"io"

	"golang.org/x/image/bmp"
	"golang.org/x/image/tiff"
	_ "golang.org/x/image/webp"
)

var _ = fmt.Print

var DecodableImageTypes = map[string]bool{
	"image/jpeg": true, "image/png": true, "image/bmp": true, "image/tiff": true, "image/webp": true, "image/gif": true,
}

var EncodableImageTypes = map[string]bool{
	"image/jpeg": true, "image/png": true, "image/bmp": true, "image/tiff": true, "image/gif": true,
}

func Encode(output io.Writer, img image.Image, format_mime string) (err error) {
	switch format_mime {
	case "image/png":
		return png.Encode(output, img)
	case "image/jpeg":
		return jpeg.Encode(output, img, nil)
	case "image/bmp":
		return bmp.Encode(output, img)
	case "image/gif":
		return gif.Encode(output, img, nil)
	case "image/tiff":
		return tiff.Encode(output, img, nil)
	}
	err = fmt.Errorf("Unsupported output image MIME type %s", format_mime)
	return

}
