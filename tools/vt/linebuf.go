package vt

import (
	"fmt"
)

var _ = fmt.Print

const extra_capacity uint = 4

type LineBuf struct {
	cells             []Cell
	attrs             []LineAttrs
	line_map, scratch []uint
	xnum, ynum        uint
}

func NewLineBuf(xnum, ynum uint) *LineBuf {
	lm := make([]uint, ynum, ynum+extra_capacity)
	var i uint
	for i = 0; i < ynum; i++ {
		lm[i] = i
	}
	return &LineBuf{
		cells:   make([]Cell, xnum*ynum, xnum*(ynum+extra_capacity)),
		attrs:   make([]LineAttrs, len(lm), cap(lm)),
		scratch: make([]uint, len(lm), cap(lm)),
		xnum:    xnum, ynum: ynum, line_map: lm,
	}
}

func (self *LineBuf) Line(y uint) Line {
	idx := self.line_map[y]
	return Line{Attrs: self.attrs[y], Cells: self.cells[idx*self.xnum : (idx+1)*self.xnum]}
}

func (self *LineBuf) AddLines(n uint) {
	ynum := self.ynum + n
	if uint(cap(self.line_map)) >= ynum {
		self.line_map = self.line_map[0:ynum:cap(self.line_map)]
		self.scratch = self.scratch[0:ynum:cap(self.scratch)]
		self.attrs = self.attrs[0:ynum:cap(self.attrs)]
		self.cells = self.cells[0 : ynum*self.xnum : cap(self.cells)]
	} else {
		newattrs := make([]LineAttrs, ynum, ynum+extra_capacity)
		copy(newattrs, self.attrs)
		newlinemap := make([]uint, ynum, ynum+extra_capacity)
		copy(newlinemap, self.line_map)
		for n = self.ynum; n < ynum; n++ {
			newlinemap[n] = n
		}
		newcells := make([]Cell, self.xnum*ynum, self.xnum*(ynum+extra_capacity))
		copy(newcells, self.cells)
		self.attrs = newattrs
		self.line_map = newlinemap
		self.cells = newcells
		self.scratch = make([]uint, len(self.line_map), cap(self.line_map))
	}
	self.ynum = ynum
}
