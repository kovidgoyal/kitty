// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"

	"golang.org/x/exp/maps"
)

var _ = fmt.Print

type Set[T comparable] struct {
	items map[T]struct{}
}

func (self *Set[T]) Add(val T) {
	self.items[val] = struct{}{}
}

func (self *Set[T]) AddItems(val ...T) {
	for _, x := range val {
		self.items[x] = struct{}{}
	}
}

func (self *Set[T]) String() string {
	return fmt.Sprintf("%#v", maps.Keys(self.items))
}

func (self *Set[T]) Remove(val T) {
	delete(self.items, val)
}

func (self *Set[T]) Discard(val T) {
	delete(self.items, val)
}

func (self *Set[T]) Has(val T) bool {
	_, ok := self.items[val]
	return ok
}

func (self *Set[T]) Len() int {
	return len(self.items)
}

func (self *Set[T]) ForEach(f func(T)) {
	for x := range self.items {
		f(x)
	}
}

func (self *Set[T]) Iterable() map[T]struct{} {
	return self.items
}

func (self *Set[T]) AsSlice() []T {
	return maps.Keys(self.items)
}

func (self *Set[T]) Intersect(other *Set[T]) (ans *Set[T]) {
	if other == nil {
		return NewSet[T]()
	}
	if self.Len() < other.Len() {
		ans = NewSet[T](self.Len())
		for x := range self.items {
			if _, ok := other.items[x]; ok {
				ans.items[x] = struct{}{}
			}
		}
	} else {
		ans = NewSet[T](other.Len())
		for x := range other.items {
			if _, ok := self.items[x]; ok {
				ans.items[x] = struct{}{}
			}
		}
	}
	return
}

func (self *Set[T]) Subtract(other *Set[T]) (ans *Set[T]) {
	ans = NewSet[T](self.Len())
	for x := range self.items {
		if other == nil || !other.Has(x) {
			ans.items[x] = struct{}{}
		}
	}
	return ans
}

func (self *Set[T]) IsSubsetOf(other *Set[T]) bool {
	if other == nil {
		return self.Len() == 0
	}
	for x := range self.items {
		if !other.Has(x) {
			return false
		}
	}
	return true
}

func NewSet[T comparable](capacity ...int) (ans *Set[T]) {
	if len(capacity) == 0 {
		ans = &Set[T]{items: make(map[T]struct{}, 8)}
	} else {
		ans = &Set[T]{items: make(map[T]struct{}, capacity[0])}
	}
	return
}

func NewSetWithItems[T comparable](items ...T) (ans *Set[T]) {
	ans = NewSet[T](len(items))
	ans.AddItems(items...)
	return ans
}
