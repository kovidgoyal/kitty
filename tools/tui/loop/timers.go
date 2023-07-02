// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"time"

	"golang.org/x/exp/slices"
)

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
	for _, t := range self.timers {
		if now.After(t.deadline) {
			err := t.callback(t.id)
			if err != nil {
				return err
			}
			if t.repeats {
				t.update_deadline(now)
				self.timers_temp = append(self.timers_temp, t)
			}
		}
	}
	self.timers = self.timers[:len(self.timers_temp)]
	if len(self.timers) > 0 {
		copy(self.timers, self.timers_temp)
		self.sort_timers()
	}
	return nil
}

func (self *Loop) sort_timers() {
	slices.SortStableFunc(self.timers, func(a, b *timer) bool { return a.deadline.Before(b.deadline) })
}
