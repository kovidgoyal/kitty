// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"sort"
	"time"
)

func (self *Loop) dispatch_timers(now time.Time) error {
	updated := false
	remove := make(map[IdType]bool, 0)
	for _, t := range self.timers {
		if now.After(t.deadline) {
			err := t.callback(t.id)
			if err != nil {
				return err
			}
			if t.repeats {
				t.update_deadline(now)
				updated = true
			} else {
				remove[t.id] = true
			}
		}
	}
	if len(remove) > 0 {
		timers := make([]*timer, len(self.timers)-len(remove))
		for _, t := range self.timers {
			if !remove[t.id] {
				timers = append(timers, t)
			}
		}
		self.timers = timers
	}
	if updated {
		self.sort_timers()
	}
	return nil
}

func (self *Loop) sort_timers() {
	sort.SliceStable(self.timers, func(a, b int) bool { return self.timers[a].deadline.Before(self.timers[b].deadline) })
}
