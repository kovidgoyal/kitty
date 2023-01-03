// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"runtime"
	"sync"
	"sync/atomic"
)

var _ = fmt.Print

type Context struct {
	num_of_threads atomic.Int32
}

func (self *Context) SetNumberOfThreads(n int) {
	self.num_of_threads.Store(int32(n))
}

func (self *Context) NumberOfThreads() int {
	return int(self.num_of_threads.Load())
}

// parallel processes the data in separate goroutines.
func (self *Context) Parallel(start, stop int, fn func(<-chan int)) {
	count := stop - start
	if count < 1 {
		return
	}

	procs := self.NumberOfThreads()
	if procs <= 0 {
		procs = runtime.NumCPU()
	}
	if procs > count {
		procs = count
	}

	c := make(chan int, count)
	for i := start; i < stop; i++ {
		c <- i
	}
	close(c)

	var wg sync.WaitGroup
	for i := 0; i < procs; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			fn(c)
		}()
	}
	wg.Wait()
}
