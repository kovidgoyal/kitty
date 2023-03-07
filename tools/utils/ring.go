// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
)

var _ = fmt.Print

func rb_min(a, b uint64) uint64 {
	if a < b {
		return a
	} else {
		return b
	}
}

type RingBuffer[T any] struct {
	buffer    []T
	read_pos  uint64
	use_count uint64
}

func NewRingBuffer[T any](size uint64) *RingBuffer[T] {
	return &RingBuffer[T]{
		buffer: make([]T, size),
	}
}

func (self *RingBuffer[T]) Len() uint64 {
	return self.use_count
}

func (self *RingBuffer[T]) Capacity() uint64 {
	return uint64(len(self.buffer))
}

func (self *RingBuffer[T]) Clear() {
	self.read_pos = 0
	self.use_count = 0
}

func (self *RingBuffer[T]) Grow(new_size uint64) {
	if new_size <= self.Capacity() {
		return
	}
	buf := make([]T, new_size)
	if self.use_count > 0 {
		self.ReadTillEmpty(buf)
	}
	self.buffer = buf
	self.read_pos = 0
}

func (self *RingBuffer[T]) WriteTillFull(p ...T) uint64 {
	ssz := self.Capacity()
	available := ssz - self.use_count
	sz := rb_min(uint64(len(p)), available)
	if sz == 0 {
		return 0
	}
	tail := (self.read_pos + self.use_count) % ssz
	write_end := (self.read_pos + self.use_count + sz) % ssz
	self.use_count += sz
	p = p[:sz]
	if tail <= write_end {
		copy(self.buffer[tail:], p)
	} else {
		first_write := ssz - tail
		copy(self.buffer[tail:], p[:first_write])
		copy(self.buffer, p[first_write:])
	}
	return sz
}

func (self *RingBuffer[T]) WriteAllAndDiscardOld(p ...T) {
	ssz := self.Capacity()
	left := uint64(len(p))
	if left >= ssz { // Fast path
		extra := left - ssz
		copy(self.buffer, p[extra:])
		self.read_pos = 0
		self.use_count = ssz
		return
	}
	for {
		written := self.WriteTillFull(p...)
		p = p[written:]
		left = uint64(len(p))
		if left == 0 {
			break
		}
		self.slices_to_read(left)
	}
}

func (self *RingBuffer[T]) ReadTillEmpty(p []T) uint64 {
	a, b := self.slices_to_read(uint64(len(p)))
	copy(p, a)
	copy(p[len(a):], b)
	return uint64(len(a)) + uint64(len(b))
}

func (self *RingBuffer[T]) ReadAll() []T {
	ans := make([]T, self.Len())
	self.ReadTillEmpty(ans)
	return ans
}

func (self *RingBuffer[T]) slices_to_read(sz uint64) ([]T, []T) {
	ssz := self.Capacity()
	sz = rb_min(sz, self.use_count)
	head := self.read_pos
	end_read := (head + sz) % ssz
	self.use_count -= sz
	self.read_pos = end_read
	if end_read > head || sz == 0 {
		return self.buffer[head:end_read], self.buffer[0:0]
	}
	first_read := ssz - head
	return self.buffer[head : head+first_read], self.buffer[0 : sz-first_read]
}
