package choose_files

import (
	"fmt"
	"io/fs"
)

var _ = fmt.Print

type CollectionIndex struct {
	Slice, Pos int
}

func (c CollectionIndex) Compare(o CollectionIndex) int {
	if c.Slice == o.Slice {
		return c.Pos - o.Pos
	}
	return c.Slice - o.Slice
}

type ResultCollection struct {
	slices     [][]ResultItem
	append_idx CollectionIndex
	batch_size int
}

func NewResultCollection(batch_size int) (ans *ResultCollection) {
	batch_size = max(1, batch_size)
	return &ResultCollection{
		batch_size: batch_size,
		slices:     [][]ResultItem{make([]ResultItem, batch_size)},
	}
}

func (c *ResultCollection) Len() int {
	return c.batch_size*(len(c.slices)-1) + c.append_idx.Pos
}

func (c *ResultCollection) NextAppendPointer() (ans *ResultItem) {
	s := c.slices[c.append_idx.Slice]
	ans = &s[c.append_idx.Pos]
	if c.append_idx.Pos+1 < len(s) {
		c.append_idx.Pos++
	} else if c.append_idx.Slice+1 < len(c.slices) {
		c.append_idx.Slice++
		c.append_idx.Pos = 0
	} else {
		c.slices = append(c.slices, make([]ResultItem, 4096))
		c.append_idx.Slice++
		c.append_idx.Pos = 0
	}
	return
}

func (c *ResultCollection) Batch(offset *CollectionIndex) (ans []ResultItem) {
	if offset.Slice == c.append_idx.Slice {
		if offset.Pos < c.append_idx.Pos {
			ans = c.slices[offset.Slice][offset.Pos:c.append_idx.Pos]
			offset.Pos = c.append_idx.Pos
		}
	} else if offset.Slice < c.append_idx.Slice {
		ans = c.slices[offset.Slice][offset.Pos:]
		offset.Slice++
		offset.Pos = 0
	}
	return
}

func (c *ResultCollection) NextDir(offset *CollectionIndex) (ans string) {
	for ans == "" && offset.Compare(c.append_idx) < 0 {
		if c.slices[offset.Slice][offset.Pos].ftype&fs.ModeDir != 0 {
			ans = c.slices[offset.Slice][offset.Pos].text
		}
		offset.Pos++
		if offset.Pos >= len(c.slices[offset.Slice]) {
			offset.Slice++
			offset.Pos = 0
		}
	}
	return
}
