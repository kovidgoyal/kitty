package vt

import (
	"fmt"
)

var _ = fmt.Print

type LineBuf struct {
	cells      []Cell
	attrs      []LineAttrs
	line_map   []uint
	xnum, ynum uint
}

func NewLineBuf(xnum, ynum uint) *LineBuf {
	lm := make([]uint, ynum, ynum)
	var i uint
	for i = 0; i < ynum; i++ {
		lm[i] = i
	}
	return &LineBuf{
		cells: make([]Cell, xnum*ynum, xnum*ynum), attrs: make([]LineAttrs, ynum, ynum), xnum: xnum, ynum: ynum, line_map: lm,
	}
}

func (self *LineBuf) Line(y uint) Line {
	idx := self.line_map[y]
	return Line{Attrs: self.attrs[y], Cells: self.cells[idx*self.xnum : (idx+1)*self.xnum]}
}

func (self *LineBuf) AddLines(n uint) {
	ynum := self.ynum + n
	if uint(cap(self.line_map)) >= ynum {
		self.line_map = self.line_map[:ynum]
		self.attrs = self.attrs[:ynum]
		self.cells = self.cells[:ynum*self.xnum]
	} else {
		const extra_capacity uint = 2
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
	}
	self.ynum = ynum
}
