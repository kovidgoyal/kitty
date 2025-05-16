// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"slices"
	"time"

	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var debugprintln = tty.DebugPrintln
var _ = debugprintln

type timer struct {
	interval time.Duration
	deadline time.Time
	repeats  bool
	id       IdType
	callback TimerCallback
}

func (self *timer) update_deadline(now time.Time) {
	self.deadline = now.Add(self.interval)
}

func (self timer) String() string {
	return fmt.Sprintf("Timer(id=%d, callback=%s, deadline=%s, repeats=%v)", self.id, utils.FunctionName(self.callback), time.Until(self.deadline), self.repeats)
}

func (self *Loop) add_timer(interval time.Duration, repeats bool, callback TimerCallback) (IdType, error) {
	if self.timers == nil {
		return 0, fmt.Errorf("Cannot add timers before starting the run loop, add them in OnInitialize instead")
	}
	self.timer_id_counter++
	t := timer{interval: interval, repeats: repeats, callback: callback, id: self.timer_id_counter}
	t.update_deadline(time.Now())
	self.timers = append(self.timers, &t)
	self.sort_timers()
	return t.id, nil
}

func (self *Loop) remove_timer(id IdType) bool {
	if self.timers == nil {
		return false
	}
	for i := 0; i < len(self.timers); i++ {
		if self.timers[i].id == id {
			self.timers = append(self.timers[:i], self.timers[i+1:]...)
			return true
		}
	}
	return false
}

func (self *Loop) dispatch_timers(now time.Time) error {
	self.timers_temp = self.timers_temp[:0]
	self.timers, self.timers_temp = self.timers_temp, self.timers
	dispatched := false
	for _, t := range self.timers_temp {
		if now.After(t.deadline) {
			dispatched = true
			err := t.callback(t.id)
			if err != nil {
				return err
			}
			if t.repeats {
				t.update_deadline(now)
				self.timers = append(self.timers, t)
			}
		} else {
			self.timers = append(self.timers, t)
		}
	}
	if dispatched {
		self.sort_timers() // needed because a timer callback could have added a new timer
	}
	return nil
}

func (self *Loop) sort_timers() {
	slices.SortStableFunc(self.timers, func(a, b *timer) int { return a.deadline.Compare(b.deadline) })
}
