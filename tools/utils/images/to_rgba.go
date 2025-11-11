// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"image"
	"math"

	"github.com/kovidgoyal/imaging"
	"github.com/kovidgoyal/imaging/nrgba"
	"github.com/kovidgoyal/kitty/tools/tty"
)

var _ = fmt.Print
var debugprintln = tty.DebugPrintln
var _ = debugprintln

func (self *Context) run_paste(src imaging.Scanner, background image.Image, pos image.Point, postprocess func([]byte)) {
	pos = pos.Sub(background.Bounds().Min)
	pasteRect := image.Rectangle{Min: pos, Max: pos.Add(src.Bounds().Size())}
	interRect := pasteRect.Intersect(background.Bounds())
	if interRect.Empty() {
		return
	}
	bytes_per_pixel := src.Num_of_channels() * src.Bytes_per_channel()
	var stride int
	var pix []uint8
	switch v := background.(type) {
	case *image.NRGBA:
		stride = v.Stride
		pix = v.Pix
	case *imaging.NRGB:
		stride = v.Stride
		pix = v.Pix
	default:
		panic(fmt.Sprintf("Unsupported image type: %v", v))
	}
	if len(pix) < background.Bounds().Dy()*stride {
		panic(fmt.Sprintf("background image has insufficient pixel data. Bounds: %v Stride: %d Data len: %d", background.Bounds(), stride, len(pix)))
	}
	if err := self.SafeParallel(interRect.Min.Y, interRect.Max.Y, func(ys <-chan int) {
		for y := range ys {
			x1 := interRect.Min.X - pasteRect.Min.X
			x2 := interRect.Max.X - pasteRect.Min.X
			y1 := y - pasteRect.Min.Y
			y2 := y1 + 1
			i1 := y*stride + interRect.Min.X*bytes_per_pixel
			i2 := i1 + interRect.Dx()*bytes_per_pixel
			dst := pix[i1:i2]
			src.Scan(x1, y1, x2, y2, dst)
			postprocess(dst)
		}
	}); err != nil {
		panic(err)
	}

}

func (self *Context) paste_nrgba_onto_opaque(background *image.NRGBA, img image.Image, pos image.Point, bgcol *imaging.NRGBColor) {
	src := nrgba.NewNRGBAScanner(img)
	if bgcol == nil {
		self.run_paste(src, background, pos, func([]byte) {})
		return
	}
	bg := [3]float64{float64(bgcol.R), float64(bgcol.G), float64(bgcol.B)}
	self.run_paste(src, background, pos, func(dst []byte) {
		for len(dst) > 0 {
			a := float64(dst[3]) / 255.0
			for i := range dst[:3] {
				// uint8() automatically converts floats greater than 255 but less than 256 to 255
				dst[i] = uint8(float64(dst[i])*a + bg[i]*(1-a))
			}
			dst[3] = 255
			dst = dst[4:]
		}

	})
}

// Paste pastes the img image to the background image at the specified position. Optionally composing onto the specified opaque color.
func (self *Context) Paste(background image.Image, img image.Image, pos image.Point, opaque_bg *imaging.NRGBColor) {
	switch b := background.(type) {
	case *image.NRGBA:
		self.paste_nrgba_onto_opaque(b, img, pos, opaque_bg)
	case *imaging.NRGB:
		self.paste_nrgb_onto_opaque(b, img, pos, opaque_bg)
	default:
		panic("Unsupported background image type")
	}
}

// PasteCenter pastes the img image to the center of the background image. Optionally composing onto the specified opaque color.
func (self *Context) PasteCenter(background image.Image, img image.Image, opaque_bg *imaging.NRGBColor) {
	bgBounds := background.Bounds()
	bgW := bgBounds.Dx()
	bgH := bgBounds.Dy()
	bgMinX := bgBounds.Min.X
	bgMinY := bgBounds.Min.Y

	centerX := bgMinX + bgW/2
	centerY := bgMinY + bgH/2

	x0 := centerX - img.Bounds().Dx()/2
	y0 := centerY - img.Bounds().Dy()/2

	self.Paste(background, img, image.Pt(x0, y0), opaque_bg)
}

func FitImage(width, height, pwidth, pheight int) (final_width int, final_height int) {
	if height > pheight {
		corrf := float64(pheight) / float64(height)
		width, height = int(math.Floor(corrf*float64(width))), pheight
	}
	if width > pwidth {
		corrf := float64(pwidth) / float64(width)
		width, height = pwidth, int(math.Floor(corrf*float64(height)))
	}
	if height > pheight {
		corrf := float64(pheight) / float64(height)
		width, height = int(math.Floor(corrf*float64(width))), pheight
	}

	return width, height
}

func NewNRGBAWithContiguousRGBAPixels(p []byte, left, top, width, height int) (*image.NRGBA, error) {
	const bpp = 4
	if expected := bpp * width * height; expected != len(p) {
		return nil, fmt.Errorf("the image width and height dont match the size of the specified pixel data: width=%d height=%d sz=%d != %d", width, height, len(p), expected)
	}
	return &image.NRGBA{
		Pix:    p,
		Stride: bpp * width,
		Rect:   image.Rectangle{image.Point{left, top}, image.Point{left + width, top + height}},
	}, nil
}
