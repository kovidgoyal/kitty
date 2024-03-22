// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"image"
	"image/color"
)

var _ = fmt.Print

type NRGBColor struct {
	R, G, B uint8
}

func (c NRGBColor) AsSharp() string {
	return fmt.Sprintf("#%02X%02X%02X", c.R, c.G, c.B)
}

func (c NRGBColor) RGBA() (r, g, b, a uint32) {
	r = uint32(c.R)
	r |= r << 8
	g = uint32(c.G)
	g |= g << 8
	b = uint32(c.B)
	b |= b << 8
	a = 65280 // ( 255 << 8 )
	return
}

// NRGB is an in-memory image whose At method returns NRGBColor values.
type NRGB struct {
	// Pix holds the image's pixels, in R, G, B, A order. The pixel at
	// (x, y) starts at Pix[(y-Rect.Min.Y)*Stride + (x-Rect.Min.X)*4].
	Pix []uint8
	// Stride is the Pix stride (in bytes) between vertically adjacent pixels.
	Stride int
	// Rect is the image's bounds.
	Rect image.Rectangle
}

func nrgbModel(c color.Color) color.Color {
	if _, ok := c.(NRGBColor); ok {
		return c
	}
	r, g, b, a := c.RGBA()
	if a == 0xffff {
		return NRGBColor{uint8(r >> 8), uint8(g >> 8), uint8(b >> 8)}
	}
	if a == 0 {
		return NRGBColor{0, 0, 0}
	}
	// Since Color.RGBA returns an alpha-premultiplied color, we should have r <= a && g <= a && b <= a.
	r = (r * 0xffff) / a
	g = (g * 0xffff) / a
	b = (b * 0xffff) / a
	return NRGBColor{uint8(r >> 8), uint8(g >> 8), uint8(b >> 8)}
}

var NRGBModel color.Model = color.ModelFunc(nrgbModel)

func (p *NRGB) ColorModel() color.Model { return NRGBModel }

func (p *NRGB) Bounds() image.Rectangle { return p.Rect }

func (p *NRGB) At(x, y int) color.Color {
	return p.NRGBAt(x, y)
}

func (p *NRGB) NRGBAt(x, y int) NRGBColor {
	if !(image.Point{x, y}.In(p.Rect)) {
		return NRGBColor{}
	}
	i := p.PixOffset(x, y)
	s := p.Pix[i : i+4 : i+4] // Small cap improves performance, see https://golang.org/issue/27857
	return NRGBColor{s[0], s[1], s[2]}
}

// PixOffset returns the index of the first element of Pix that corresponds to
// the pixel at (x, y).
func (p *NRGB) PixOffset(x, y int) int {
	return (y-p.Rect.Min.Y)*p.Stride + (x-p.Rect.Min.X)*4
}

func (p *NRGB) Set(x, y int, c color.Color) {
	if !(image.Point{x, y}.In(p.Rect)) {
		return
	}
	i := p.PixOffset(x, y)
	c1 := NRGBModel.Convert(c).(NRGBColor)
	s := p.Pix[i : i+3 : i+3] // Small cap improves performance, see https://golang.org/issue/27857
	s[0] = c1.R
	s[1] = c1.G
	s[2] = c1.B
}

func (p *NRGB) SetRGBA64(x, y int, c color.RGBA64) {
	if !(image.Point{x, y}.In(p.Rect)) {
		return
	}
	r, g, b, a := uint32(c.R), uint32(c.G), uint32(c.B), uint32(c.A)
	if (a != 0) && (a != 0xffff) {
		r = (r * 0xffff) / a
		g = (g * 0xffff) / a
		b = (b * 0xffff) / a
	}
	i := p.PixOffset(x, y)
	s := p.Pix[i : i+3 : i+3] // Small cap improves performance, see https://golang.org/issue/27857
	s[0] = uint8(r >> 8)
	s[1] = uint8(g >> 8)
	s[2] = uint8(b >> 8)
}

func (p *NRGB) SetNRGBA(x, y int, c color.NRGBA) {
	if !(image.Point{x, y}.In(p.Rect)) {
		return
	}
	i := p.PixOffset(x, y)
	s := p.Pix[i : i+3 : i+3] // Small cap improves performance, see https://golang.org/issue/27857
	s[0] = c.R
	s[1] = c.G
	s[2] = c.B
}

// SubImage returns an image representing the portion of the image p visible
// through r. The returned value shares pixels with the original image.
func (p *NRGB) SubImage(r image.Rectangle) image.Image {
	r = r.Intersect(p.Rect)
	// If r1 and r2 are Rectangles, r1.Intersect(r2) is not guaranteed to be inside
	// either r1 or r2 if the intersection is empty. Without explicitly checking for
	// this, the Pix[i:] expression below can panic.
	if r.Empty() {
		return &NRGB{}
	}
	i := p.PixOffset(r.Min.X, r.Min.Y)
	return &NRGB{
		Pix:    p.Pix[i:],
		Stride: p.Stride,
		Rect:   r,
	}
}

// Opaque scans the entire image and reports whether it is fully opaque.
func (p *NRGB) Opaque() bool { return true }

type scanner_rgb struct {
	image            image.Image
	w, h             int
	palette          []NRGBColor
	opaque_base      []float64
	opaque_base_uint []uint8
}

func (s scanner_rgb) bytes_per_pixel() int    { return 3 }
func (s scanner_rgb) bounds() image.Rectangle { return s.image.Bounds() }

func blend(dest []uint8, base []float64, r, g, b, a uint8) {
	alpha := float64(a) / 255.0
	dest[0] = uint8(alpha*float64(r) + (1.0-alpha)*base[0])
	dest[1] = uint8(alpha*float64(g) + (1.0-alpha)*base[1])
	dest[2] = uint8(alpha*float64(b) + (1.0-alpha)*base[2])
}

func newScannerRGB(img image.Image, opaque_base NRGBColor) *scanner_rgb {
	s := &scanner_rgb{
		image: img, w: img.Bounds().Dx(), h: img.Bounds().Dy(),
		opaque_base:      []float64{float64(opaque_base.R), float64(opaque_base.G), float64(opaque_base.B)}[0:3:3],
		opaque_base_uint: []uint8{opaque_base.R, opaque_base.G, opaque_base.B}[0:3:3],
	}
	if img, ok := img.(*image.Paletted); ok {
		s.palette = make([]NRGBColor, max(256, len(img.Palette)))
		d := make([]uint8, 3)
		for i := 0; i < len(img.Palette); i++ {
			r, g, b, a := img.Palette[i].RGBA()
			switch a {
			case 0:
				s.palette[i] = opaque_base
			default:
				blend(d, s.opaque_base, uint8((r*0xffff/a)>>8), uint8((g*0xffff/a)>>8), uint8((b*0xffff/a)>>8), uint8(a>>8))
				s.palette[i] = NRGBColor{d[0], d[1], d[2]}
			}
		}
	}
	return s
}

// scan scans the given rectangular region of the image into dst.
func (s *scanner_rgb) scan(x1, y1, x2, y2 int, dst []uint8) {
	switch img := s.image.(type) {
	case *image.NRGBA:
		j := 0
		for y := y1; y < y2; y++ {
			i := y*img.Stride + x1*4
			for x := x1; x < x2; x++ {
				blend(dst[j:j+3:j+3], s.opaque_base, img.Pix[i], img.Pix[i+1], img.Pix[i+2], img.Pix[i+3])
				j += 3
				i += 4
			}
		}

	case *image.NRGBA64:
		j := 0
		for y := y1; y < y2; y++ {
			i := y*img.Stride + x1*8
			for x := x1; x < x2; x++ {
				blend(dst[j:j+3:j+3], s.opaque_base, img.Pix[i], img.Pix[i+2], img.Pix[i+4], img.Pix[i+6])
				j += 3
				i += 8
			}
		}

	case *image.RGBA:
		j := 0
		for y := y1; y < y2; y++ {
			i := y*img.Stride + x1*4
			for x := x1; x < x2; x++ {
				d := dst[j : j+3 : j+3]
				a := img.Pix[i+3]
				switch a {
				case 0:
					d[0] = s.opaque_base_uint[0]
					d[1] = s.opaque_base_uint[1]
					d[2] = s.opaque_base_uint[2]
				case 0xff:
					s := img.Pix[i : i+3 : i+3]
					d[0] = s[0]
					d[1] = s[1]
					d[2] = s[2]
				default:
					r16 := uint16(img.Pix[i])
					g16 := uint16(img.Pix[i+1])
					b16 := uint16(img.Pix[i+2])
					a16 := uint16(a)
					blend(d, s.opaque_base, uint8(r16*0xff/a16), uint8(g16*0xff/a16), uint8(b16*0xff/a16), a)
				}
				j += 3
				i += 4
			}
		}

	case *image.RGBA64:
		j := 0
		for y := y1; y < y2; y++ {
			i := y*img.Stride + x1*8
			for x := x1; x < x2; x++ {
				src := img.Pix[i : i+8 : i+8]
				d := dst[j : j+3 : j+3]
				a := src[6]
				switch a {
				case 0:
					d[0] = s.opaque_base_uint[0]
					d[1] = s.opaque_base_uint[1]
					d[2] = s.opaque_base_uint[2]
				case 0xff:
					d[0] = src[0]
					d[1] = src[2]
					d[2] = src[4]
				default:
					r32 := uint32(src[0])<<8 | uint32(src[1])
					g32 := uint32(src[2])<<8 | uint32(src[3])
					b32 := uint32(src[4])<<8 | uint32(src[5])
					a32 := uint32(src[6])<<8 | uint32(src[7])
					blend(d, s.opaque_base, uint8((r32*0xffff/a32)>>8), uint8((g32*0xffff/a32)>>8), uint8((b32*0xffff/a32)>>8), a)
				}
				j += 3
				i += 8
			}
		}

	case *image.Gray:
		j := 0
		for y := y1; y < y2; y++ {
			i := y*img.Stride + x1
			for x := x1; x < x2; x++ {
				c := img.Pix[i]
				d := dst[j : j+3 : j+3]
				d[0] = c
				d[1] = c
				d[2] = c
				j += 3
				i++
			}
		}

	case *image.Gray16:
		j := 0
		for y := y1; y < y2; y++ {
			i := y*img.Stride + x1*2
			for x := x1; x < x2; x++ {
				c := img.Pix[i]
				d := dst[j : j+3 : j+3]
				d[0] = c
				d[1] = c
				d[2] = c
				j += 3
				i += 2
			}
		}

	case *image.YCbCr:
		j := 0
		x1 += img.Rect.Min.X
		x2 += img.Rect.Min.X
		y1 += img.Rect.Min.Y
		y2 += img.Rect.Min.Y

		hy := img.Rect.Min.Y / 2
		hx := img.Rect.Min.X / 2
		for y := y1; y < y2; y++ {
			iy := (y-img.Rect.Min.Y)*img.YStride + (x1 - img.Rect.Min.X)

			var yBase int
			switch img.SubsampleRatio {
			case image.YCbCrSubsampleRatio444, image.YCbCrSubsampleRatio422:
				yBase = (y - img.Rect.Min.Y) * img.CStride
			case image.YCbCrSubsampleRatio420, image.YCbCrSubsampleRatio440:
				yBase = (y/2 - hy) * img.CStride
			}

			for x := x1; x < x2; x++ {
				var ic int
				switch img.SubsampleRatio {
				case image.YCbCrSubsampleRatio444, image.YCbCrSubsampleRatio440:
					ic = yBase + (x - img.Rect.Min.X)
				case image.YCbCrSubsampleRatio422, image.YCbCrSubsampleRatio420:
					ic = yBase + (x/2 - hx)
				default:
					ic = img.COffset(x, y)
				}

				yy1 := int32(img.Y[iy]) * 0x10101
				cb1 := int32(img.Cb[ic]) - 128
				cr1 := int32(img.Cr[ic]) - 128

				r := yy1 + 91881*cr1
				if uint32(r)&0xff000000 == 0 {
					r >>= 16
				} else {
					r = ^(r >> 31)
				}

				g := yy1 - 22554*cb1 - 46802*cr1
				if uint32(g)&0xff000000 == 0 {
					g >>= 16
				} else {
					g = ^(g >> 31)
				}

				b := yy1 + 116130*cb1
				if uint32(b)&0xff000000 == 0 {
					b >>= 16
				} else {
					b = ^(b >> 31)
				}

				d := dst[j : j+3 : j+3]
				d[0] = uint8(r)
				d[1] = uint8(g)
				d[2] = uint8(b)

				iy++
				j += 3
			}
		}

	case *image.Paletted:
		j := 0
		for y := y1; y < y2; y++ {
			i := y*img.Stride + x1
			for x := x1; x < x2; x++ {
				c := s.palette[img.Pix[i]]
				d := dst[j : j+3 : j+3]
				d[0] = c.R
				d[1] = c.G
				d[2] = c.B
				j += 3
				i++
			}
		}

	default:
		j := 0
		b := s.image.Bounds()
		x1 += b.Min.X
		x2 += b.Min.X
		y1 += b.Min.Y
		y2 += b.Min.Y
		for y := y1; y < y2; y++ {
			for x := x1; x < x2; x++ {
				r16, g16, b16, a16 := s.image.At(x, y).RGBA()
				d := dst[j : j+3 : j+3]
				switch a16 {
				case 0xffff:
					d[0] = uint8(r16 >> 8)
					d[1] = uint8(g16 >> 8)
					d[2] = uint8(b16 >> 8)
				case 0:
					d[0] = s.opaque_base_uint[0]
					d[1] = s.opaque_base_uint[1]
					d[2] = s.opaque_base_uint[2]
				default:
					blend(d, s.opaque_base, uint8(((r16*0xffff)/a16)>>8), uint8(((g16*0xffff)/a16)>>8), uint8(((b16*0xffff)/a16)>>8), uint8(a16>>8))
				}
				j += 3
			}
		}
	}
}

func (self *Context) paste_nrgb_onto_opaque(background *NRGB, img image.Image, pos image.Point, bgcol *NRGBColor) {
	bg := NRGBColor{}
	if bgcol != nil {
		bg = *bgcol

	}
	src := newScannerRGB(img, bg)
	self.run_paste(src, background, pos, func(dst []byte) {})
}

func NewNRGB(r image.Rectangle) *NRGB {
	return &NRGB{
		Pix:    make([]uint8, 3*r.Dx()*r.Dy()),
		Stride: 3 * r.Dx(),
		Rect:   r,
	}
}
