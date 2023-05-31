// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"time"
)

var _ = fmt.Print

type Spinner struct {
	Name           string
	interval       time.Duration
	frames         []string
	current_frame  int
	last_change_at time.Time
}

func (self Spinner) Interval() time.Duration {
	return self.interval
}

func (self *Spinner) Tick() string {
	now := time.Now()
	if now.Sub(self.last_change_at) >= self.interval {
		self.last_change_at = now
		self.current_frame = (self.current_frame + 1) % len(self.frames)
	}
	return self.frames[self.current_frame]
}
