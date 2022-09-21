// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"sync"

	"github.com/gammazero/deque"
)

var _ = fmt.Print

type LRUCache[K comparable, V any] struct {
	data     map[K]V
	lock     sync.RWMutex
	max_size int
	lru      deque.Deque[K]
}

func NewLRUCache[K comparable, V any](max_size int) *LRUCache[K, V] {
	ans := LRUCache[K, V]{data: map[K]V{}, max_size: max_size}
	return &ans
}

func (self *LRUCache[K, V]) GetOrCreate(key K, create func(key K) (V, error)) (V, error) {
	self.lock.RLock()
	ans, found := self.data[key]
	self.lock.RUnlock()
	if found {
		return ans, nil
	}
	ans, err := create(key)
	if err == nil {
		self.lock.Lock()
		self.data[key] = ans
		self.lru.PushFront(key)
		if self.max_size > 0 && self.lru.Len() > self.max_size {
			k := self.lru.PopBack()
			delete(self.data, k)
		}
		self.lock.Unlock()
	}
	return ans, err
}

func (self *LRUCache[K, V]) MustGetOrCreate(key K, create func(key K) V) V {
	self.lock.RLock()
	ans, found := self.data[key]
	self.lock.RUnlock()
	if found {
		return ans
	}
	ans = create(key)
	self.lock.Lock()
	self.data[key] = ans
	self.lock.Unlock()
	return ans
}
