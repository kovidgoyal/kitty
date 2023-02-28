// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"sync"
	"sync/atomic"
)

var _ = fmt.Print

type Once[T any] struct {
	done       uint32
	mutex      sync.Mutex
	cached_val T

	Run func() T
}

func (self *Once[T]) Get() T {
	if atomic.LoadUint32(&self.done) == 0 {
		self.do_slow()
	}
	return self.cached_val
}

func (self *Once[T]) do_slow() {
	self.mutex.Lock()
	defer self.mutex.Unlock()
	if atomic.LoadUint32(&self.done) == 0 {
		defer atomic.StoreUint32(&self.done, 1)
		self.cached_val = self.Run()
	}
}
