// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package wcswidth

import (
	"fmt"
)

var _ = fmt.Print

type current_cell struct {
	head, tail, width int
}

type forward_iterator struct {
	width_iter    *WCWidthIterator
	current_cell  current_cell
	cell_num, pos int
}

type reverse_iterator struct {
	cells []string
	pos   int
}

func (self *forward_iterator) reset() {
	self.width_iter.Reset()
	self.current_cell = current_cell{}
	self.pos = 0
	self.cell_num = 0
}

type CellIterator struct {
	text, current string
	forward_iter  forward_iterator
	reverse_iter  reverse_iterator
}

func NewCellIterator(text string) *CellIterator {
	ans := &CellIterator{text: text}
	ans.forward_iter.width_iter = CreateWCWidthIterator()
	return ans
}

func (self *CellIterator) GotoStart() *CellIterator {
	self.forward_iter.reset()
	self.reverse_iter.pos = -1
	self.current = ""
	return self
}

func (self *CellIterator) GotoEnd() *CellIterator {
	self.current = ""
	self.reverse_iter.pos = len(self.reverse_iter.cells)
	self.forward_iter.pos = len(self.text)
	self.forward_iter.cell_num = len(self.text) + 1
	return self
}

func (self *CellIterator) Current() string { return self.current }

func (self *CellIterator) forward_one_rune() bool {
	for self.forward_iter.pos < len(self.text) {
		rune_count_before := self.forward_iter.width_iter.rune_count
		self.forward_iter.width_iter.ParseByte(self.text[self.forward_iter.pos])
		self.forward_iter.pos++
		if self.forward_iter.width_iter.rune_count != rune_count_before {
			return true
		}
	}
	return false
}

func (self *CellIterator) Forward() (has_more bool) {
	if self.reverse_iter.cells != nil {
		if self.reverse_iter.pos < len(self.reverse_iter.cells) {
			self.reverse_iter.pos++
		}
		if self.reverse_iter.pos >= len(self.reverse_iter.cells) {
			self.current = ""
			return false
		}
		self.current = self.reverse_iter.cells[self.reverse_iter.pos]
		return true
	}
	fi := &self.forward_iter
	cc := &fi.current_cell
	for {
		width_before := fi.width_iter.current_width
		pos_before := fi.pos
		if !self.forward_one_rune() {
			break
		}
		change_in_width := fi.width_iter.current_width - width_before
		cc.tail = fi.pos
		if cc.width > 0 && change_in_width > 0 {
			self.current = self.text[cc.head:pos_before]
			cc.width = change_in_width
			cc.head = pos_before
			fi.cell_num++
			return true
		}
		cc.width += change_in_width
	}
	if cc.tail > cc.head {
		self.current = self.text[cc.head:cc.tail]
		cc.head = fi.pos
		cc.tail = fi.pos
		cc.width = 0
		fi.cell_num++
		return true
	}
	self.current = ""
	return false
}

func (self *CellIterator) Backward() (has_more bool) {
	ri := &self.reverse_iter
	if ri.cells == nil {
		current_cell_num := self.forward_iter.cell_num
		cells := make([]string, 0, len(self.text))
		self.GotoStart()
		for self.Forward() {
			cells = append(cells, self.current)
		}
		ri.pos = min(max(-1, current_cell_num-1), len(cells))
		ri.cells = cells
	}
	if ri.pos > -1 {
		ri.pos--
	}
	if ri.pos < 0 {
		self.current = ""
		return false
	}
	self.current = ri.cells[ri.pos]
	return true
}
