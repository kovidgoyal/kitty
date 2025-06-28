package choose_files

import (
	"fmt"
	"io/fs"
	"slices"
	"sync"
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

func (c *CollectionIndex) NextSlice() {
	c.Slice++
	c.Pos = 0
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
		c.append_idx.NextSlice()
	} else {
		c.slices = append(c.slices, make([]ResultItem, 4096))
		c.append_idx.NextSlice()
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
		offset.NextSlice()
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
			offset.NextSlice()
		}
	}
	return
}

type SortedResults struct {
	slices [][]*ResultItem
	mutex  sync.Mutex
	len    int
}

func NewSortedResults() *SortedResults { return &SortedResults{} }
func (s *SortedResults) lock()         { s.mutex.Lock() }
func (s *SortedResults) unlock()       { s.mutex.Unlock() }

func (s *SortedResults) Len() int {
	s.lock()
	defer s.unlock()
	return s.len
}

func (s *SortedResults) At(pos CollectionIndex) (ans *ResultItem) {
	s.lock()
	defer s.unlock()
	if pos.Slice < len(s.slices) {
		s := s.slices[pos.Slice]
		if pos.Pos < len(s) {
			ans = s[pos.Pos]
		}
	}
	return
}

func (s *SortedResults) RenderedMatches(pos CollectionIndex, max_num int) (ans []*ResultItem) {
	s.lock()
	defer s.unlock()
	if pos.Slice >= len(s.slices) {
		return
	}
	ans = make([]*ResultItem, 0, max_num)
	for ; pos.Slice < len(s.slices) && max_num > 0; pos.NextSlice() {
		sl := s.slices[pos.Slice]
		if pos.Pos >= len(sl) {
			continue
		}
		sl = sl[pos.Pos:min(len(sl), pos.Pos+max_num)]
		ans = append(ans, sl...)
		max_num -= len(sl)
	}
	return
}

func (s *SortedResults) merge_slice(idx int, sl []*ResultItem) {
	sz := len(s.slices[idx])
	maxs := sl[len(sl)-1].score
	limit := idx + 1
	for limit < len(s.slices) {
		q := s.slices[limit]
		if q[0].score > maxs {
			break
		}
		sz += len(q)
		limit++
	}
	ans := make([]*ResultItem, 0, sz)
	a := 0
	b := CollectionIndex{Slice: idx}
	ss := s.slices[b.Slice]
	for a < len(sl) {
		if sl[a].score <= ss[b.Pos].score {
			ans = append(ans, sl[a])
			a++
		} else {
			ans = append(ans, ss[b.Pos])
			b.Pos++
			if b.Pos >= len(ss) {
				b.NextSlice()
				if b.Slice >= limit {
					break
				}
				ss = s.slices[b.Slice]
			}
		}
	}
	ans = append(ans, sl[a:]...)
	for ; b.Slice < limit; b.NextSlice() {
		ans = append(ans, s.slices[b.Slice][b.Pos:]...)
	}
	s.slices = slices.Replace(s.slices, idx, limit, ans)
}

func (s *SortedResults) AddSortedSlice(sl []*ResultItem) {
	if len(sl) == 0 {
		return
	}
	s.lock()
	defer s.unlock()
	s.len += len(sl)
	if len(s.slices) == 0 {
		s.slices = append(s.slices, sl)
		return
	}
	sl_min, sl_max := sl[0].score, sl[len(sl)-1].score
	for i, q := range s.slices {
		switch {
		case sl_max <= q[0].score:
			s.slices = slices.Insert(s.slices, i, sl)
			return
		case sl_min >= q[len(q)-1].score:
			continue
		default:
			s.merge_slice(i, sl)
			return
		}
	}
	s.slices = append(s.slices, sl)
}
