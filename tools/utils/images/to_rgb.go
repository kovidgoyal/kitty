// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"image"

	"github.com/kovidgoyal/imaging"
)

var _ = fmt.Print

func (self *Context) paste_nrgb_onto_opaque(background *imaging.NRGB, img image.Image, pos image.Point, bgcol *imaging.NRGBColor) {
	bg := imaging.NRGBColor{}
	if bgcol != nil {
		bg = *bgcol

	}
	src := imaging.NewNRGBScanner(img, bg)
	self.run_paste(src, background, pos, func(dst []byte) {})
}
