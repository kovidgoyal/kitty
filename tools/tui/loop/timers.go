// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"sort"
	"time"
)

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
