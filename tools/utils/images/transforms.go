// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
)

var _ = fmt.Print

func reverse_row(bytes_per_pixel int, pix []uint8) {
	if len(pix) <= bytes_per_pixel {
		return
	}
	i := 0
	j := len(pix) - bytes_per_pixel
	for i < j {
		pi := pix[i : i+bytes_per_pixel : i+bytes_per_pixel]
		pj := pix[j : j+bytes_per_pixel : j+bytes_per_pixel]
		for x := 0; x < bytes_per_pixel; x++ {
			pi[x], pj[x] = pj[x], pi[x]
		}
		i += bytes_per_pixel
		j -= bytes_per_pixel
	}
}

func (self *Context) FlipPixelsH(bytes_per_pixel, width, height int, pix []uint8) {
	stride := bytes_per_pixel * width
	self.Parallel(0, height, func(ys <-chan int) {
		for y := range ys {
			i := y * stride
			reverse_row(bytes_per_pixel, pix[i:i+stride])
		}
	})
}

func (self *Context) FlipPixelsV(bytes_per_pixel, width, height int, pix []uint8) {
	stride := bytes_per_pixel * width
	num := height / 2
	self.Parallel(0, num, func(ys <-chan int) {
		for y := range ys {
			upper := y
			lower := height - 1 - y
			a := upper * stride
			b := lower * stride
			as := pix[a : a+stride : a+stride]
			bs := pix[b : b+stride : b+stride]
			for i := range as {
				as[i], bs[i] = bs[i], as[i]
			}
		}
	})

}
