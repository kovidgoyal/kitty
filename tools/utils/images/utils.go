// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"runtime"
	"sync"
	"sync/atomic"

	"github.com/kovidgoyal/kitty/tools/utils"
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

func (self *Context) EffectiveNumberOfThreads() int {
	ans := int(self.num_of_threads.Load())
	if ans <= 0 {
		ans = max(1, runtime.NumCPU())
	}
	return ans
}

// parallel processes the data in separate goroutines. If any of them panics,
// returns an error. Note that if multiple goroutines panic, only one error is
// returned.
func (self *Context) SafeParallel(start, stop int, fn func(<-chan int)) (err error) {
	count := stop - start
	if count < 1 {
		return
	}

	procs := min(self.EffectiveNumberOfThreads(), count)
	c := make(chan int, count)
	for i := start; i < stop; i++ {
		c <- i
	}
	close(c)

	var wg sync.WaitGroup
	for range procs {
		wg.Add(1)
		go func() {
			defer func() {
				if r := recover(); r != nil {
					text, _ := utils.Format_stacktrace_on_panic(r)
					err = fmt.Errorf("%s", text)
				}
				wg.Done()
			}()
			fn(c)
		}()
	}
	wg.Wait()
	return
}
