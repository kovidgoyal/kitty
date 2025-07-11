package choose_files

import (
	"fmt"
	"io/fs"
	"slices"
	"sync"

	"github.com/kovidgoyal/kitty/tools/utils"
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

func (c CollectionIndex) Less(o CollectionIndex) bool {
	return c.Slice < o.Slice || (c.Slice == o.Slice && c.Pos < o.Pos)
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

func (c *ResultCollection) NextDir(offset *CollectionIndex) (ans string, ignore_files []ignore_file_with_prefix) {
	for ans == "" && offset.Compare(c.append_idx) < 0 {
		if c.slices[offset.Slice][offset.Pos].ftype&fs.ModeDir != 0 {
			ans = c.slices[offset.Slice][offset.Pos].text
			ignore_files = c.slices[offset.Slice][offset.Pos].ignore_files
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

func (s *SortedResults) Clear() {
	s.lock()
	defer s.unlock()
	s.slices = nil
	s.len = 0
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
	if max_num < 0 {
		max_num = s.len
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

func (s *SortedResults) Apply(first, last CollectionIndex, action func(*ResultItem) (keep_going bool)) {
	s.lock()
	defer s.unlock()
	if first.Slice >= len(s.slices) || first.Pos >= len(s.slices[first.Slice]) {
		return
	}
	amt := utils.IfElse(first.Less(last), 1, -1)
	var did_wrap bool
	for {
		if !action(s.slices[first.Slice][first.Pos]) {
			break
		}
		if first.Compare(last) == 0 {
			break
		}
		first, did_wrap = s.increment_with_wrap_around(first, amt)
		if did_wrap {
			break
		}
	}
}

func (s *SortedResults) Closest(idx CollectionIndex, matches func(*ResultItem) bool) *CollectionIndex {
	s.lock()
	defer s.unlock()
	if idx.Slice >= len(s.slices) || idx.Pos >= len(s.slices[idx.Slice]) {
		return nil
	}

	type result struct {
		idx   CollectionIndex
		count int
	}
	var a, b result
	iterate := func(idx CollectionIndex, amt int, result *result) {
		var did_wrap bool
		var count int
		result.count = -1
		for {
			idx, did_wrap = s.increment_with_wrap_around(idx, amt)
			if did_wrap {
				break
			}
			count++
			if matches(s.slices[idx.Slice][idx.Pos]) {
				result.idx = idx
				result.count = count
				break
			}
		}
	}
	go func() { iterate(idx, 1, &a) }()
	go func() { iterate(idx, -1, &a) }()
	if a.count < 0 && b.count < 0 {
		return nil
	}
	return utils.IfElse(a.count < b.count, &b.idx, &a.idx)
}

func (s *SortedResults) IncrementIndexWithWrapAroundAndCheck(idx CollectionIndex, amt int) (ans CollectionIndex, did_wrap bool) {
	s.lock()
	defer s.unlock()
	return s.increment_with_wrap_around(idx, amt)
}

func (s *SortedResults) IncrementIndexWithWrapAround(idx CollectionIndex, amt int) CollectionIndex {
	s.lock()
	defer s.unlock()
	ans, _ := s.increment_with_wrap_around(idx, amt)
	return ans
}

func (s *SortedResults) increment_with_wrap_around(idx CollectionIndex, amt int) (CollectionIndex, bool) {
	did_wrap := false
	if amt > 0 {
		for amt > 0 {
			if delta := min(amt, len(s.slices[idx.Slice])-1-idx.Pos); delta > 0 {
				idx.Pos += delta
				amt -= delta
			} else {
				idx.NextSlice()
				if idx.Slice >= len(s.slices) {
					idx = CollectionIndex{} // wraparound
					did_wrap = true
				}
				amt--
			}
		}
	} else {
		// we use separate code for negative increment instead of doing
		// increment = len - increment as it is faster in the common case of
		// increment much smaller than len
		amt *= -1
		for amt > 0 {
			if idx.Pos > 0 {
				delta := min(amt, idx.Pos)
				amt -= delta
				idx.Pos -= delta
			} else {
				if idx.Slice == 0 {
					idx = CollectionIndex{Slice: len(s.slices) - 1, Pos: len(s.slices[len(s.slices)-1]) - 1}
					did_wrap = true
				} else {
					idx.Slice--
					idx.Pos = len(s.slices[idx.Slice]) - 1
				}
				amt--
			}
		}
	}
	return idx, did_wrap
}

// Return a - b
func (s *SortedResults) SignedDistance(a, b CollectionIndex) (ans int) {
	s.lock()
	defer s.unlock()
	return s.signed_distance(a, b)
}

// Return a - b
func (s *SortedResults) signed_distance(a, b CollectionIndex) (ans int) {
	mult := -1
	if b.Less(a) {
		a, b = b, a
		mult = 1
	}
	limit := min(b.Slice, len(s.slices))
	for ; a.Slice < limit; a.NextSlice() {
		ans += len(s.slices[a.Slice]) - a.Pos
	}
	return mult * (ans + (b.Pos - a.Pos))
}

// Return |a - b|
func (s *SortedResults) distance(a, b CollectionIndex) (ans int) {
	if b.Less(a) {
		a, b = b, a
	}
	limit := min(b.Slice, len(s.slices))
	for ; a.Slice < limit; a.NextSlice() {
		ans += len(s.slices[a.Slice]) - a.Pos
	}
	return ans + (b.Pos - a.Pos)
}

func (s *SortedResults) SplitIntoColumns(calc_num_cols func(int) int, num_per_column, num_before_current int, current CollectionIndex) (ans [][]*ResultItem, num_before int, first_idx CollectionIndex) {
	s.lock()
	defer s.unlock()
	num_cols := calc_num_cols(s.len)
	total := num_cols * num_per_column
	if total < 1 {
		return nil, 0, CollectionIndex{}
	}
	num_before = min(total-1, num_before_current)
	idx, did_wrap := s.increment_with_wrap_around(current, -num_before)
	last_slice := s.slices[len(s.slices)-1]
	last := CollectionIndex{Slice: len(s.slices) - 1, Pos: len(last_slice) - 1}
	if did_wrap {
		idx = CollectionIndex{}
	} else if s.distance(idx, last) < total-1 {
		if idx, did_wrap = s.increment_with_wrap_around(last, 1-total); did_wrap {
			idx = CollectionIndex{}
		}
	}
	first_idx = idx
	num_before = s.distance(idx, current)
	// fmt.Printf("111111 idx: %v current: %v num_before: %d\n", idx, current, num_before)
	ans = make([][]*ResultItem, num_cols)
	for colidx := range len(ans) {
		col := make([]*ResultItem, 0, num_per_column)
		for len(col) < num_per_column && idx.Slice < len(s.slices) {
			ss := s.slices[idx.Slice]
			limit := min(len(ss), idx.Pos+num_per_column-len(col))
			col = append(col, ss[idx.Pos:limit]...)
			idx.Pos = limit
			if idx.Pos >= len(ss) {
				idx.NextSlice()
				if idx.Slice >= len(s.slices) {
					break
				}
			}
		}
		ans[colidx] = col
	}
	return
}
