// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"

	"kitty/tools/cli"
)

var _ = fmt.Print

type completion struct {
	before_cursor, after_cursor   string
	results                       *cli.Completions
	results_displayed, forwards   bool
	num_of_matches, current_match int
}

func (self *completion) initialize() {
	self.num_of_matches = 0
	if self.results != nil {
		for _, g := range self.results.Groups {
			self.num_of_matches += len(g.Matches)
		}
	}
	self.current_match = -1
	if !self.forwards {
		self.current_match = self.num_of_matches
	}
	if self.num_of_matches == 1 {
		self.current_match = 0
	}
}

func (self *completion) current_match_text() string {
	if self.results != nil {
		i := 0
		for _, g := range self.results.Groups {
			for _, m := range g.Matches {
				if i == self.current_match {
					return m.Word
				}
				i++
			}
		}
	}
	return ""
}

type completions struct {
	completer CompleterFunction
	current   completion
}

func (self *Readline) complete(forwards bool, repeat_count uint) bool {
	c := &self.completions
	if c.completer == nil {
		return false
	}
	if self.last_action == ActionCompleteForward || self.last_action == ActionCompleteBackward {
		delta := -1
		if forwards {
			delta = 1
		}
		delta *= int(repeat_count)
		c.current.current_match = (c.current.current_match + delta + c.current.num_of_matches) % c.current.num_of_matches
		repeat_count = 0
	} else {
		before, after := self.text_upto_cursor_pos(), self.text_after_cursor_pos()
		if before == "" {
			return false
		}
		c.current = completion{before_cursor: before, after_cursor: after, forwards: forwards, results: c.completer(before, after)}
		c.current.initialize()
		if repeat_count > 0 {
			repeat_count--
		}
	}
	c.current.forwards = forwards
	if c.current.results == nil {
		return false
	}
	ct := c.current.current_match_text()
	if ct != "" {
	}
	if repeat_count > 0 {
		self.complete(forwards, repeat_count)
	}
	return true
}
