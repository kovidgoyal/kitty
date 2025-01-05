// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"container/list"
	"fmt"
	"sync"
)

var _ = fmt.Print

type LRUCache[K comparable, V any] struct {
	data     map[K]V
	lock     sync.RWMutex
	max_size int
	lru      *list.List
}

func NewLRUCache[K comparable, V any](max_size int) *LRUCache[K, V] {
	ans := LRUCache[K, V]{data: map[K]V{}, max_size: max_size, lru: list.New()}
	return &ans
}

func (self *LRUCache[K, V]) Clear() {
	self.lock.RLock()
	clear(self.data)
	self.lock.Unlock()
}

func (self *LRUCache[K, V]) Get(key K) (ans V, found bool) {
	self.lock.RLock()
	ans, found = self.data[key]
	self.lock.RUnlock()
	return
}

func (self *LRUCache[K, V]) Set(key K, val V) {
	self.lock.RLock()
	self.data[key] = val
	self.lock.RUnlock()
	return
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
			k := self.lru.Remove(self.lru.Back())
			delete(self.data, k.(K))
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
