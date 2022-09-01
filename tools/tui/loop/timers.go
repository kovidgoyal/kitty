// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"sort"
	"time"
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
	updated := false
	self.timers_temp = self.timers_temp[:0]
	self.timers_temp = append(self.timers_temp, self.timers...)
	for i, t := range self.timers_temp {
		if now.After(t.deadline) {
			err := t.callback(t.id)
			if err != nil {
				return err
			}
			if t.repeats {
				t.update_deadline(now)
				updated = true
			} else {
				self.timers = append(self.timers[:i], self.timers[i+1:]...)
			}
		}
	}
	if updated {
		self.sort_timers()
	}
	return nil
}

func (self *Loop) sort_timers() {
	sort.SliceStable(self.timers, func(a, b int) bool { return self.timers[a].deadline.Before(self.timers[b].deadline) })
}
