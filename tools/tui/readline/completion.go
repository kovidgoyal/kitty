// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type completion struct {
	before_cursor, after_cursor   string
	results                       *cli.Completions
	results_displayed, forwards   bool
	num_of_matches, current_match int
	rendered_at_screen_width      int
	rendered_lines                []string
	last_rendered_above           bool
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
					t := m.Word
					if !g.NoTrailingSpace && t != "" {
						t += " "
					}
					return t
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
		if c.current.num_of_matches == 0 {
			return false
		}
		delta := -1
		if forwards {
			delta = 1
		}
		repeat_count %= uint(c.current.num_of_matches)
		delta *= int(repeat_count)
		c.current.current_match = (c.current.current_match + delta + c.current.num_of_matches) % c.current.num_of_matches
		repeat_count = 0
	} else {
		before, after := self.text_upto_cursor_pos(), self.text_after_cursor_pos()
		c.current = completion{before_cursor: before, after_cursor: after, forwards: forwards, results: c.completer(before, after)}
		c.current.initialize()
		if repeat_count > 0 {
			repeat_count--
		}
		if c.current.current_match != 0 {
			if self.loop != nil {
				self.loop.Beep()
			}
		}
	}
	c.current.forwards = forwards
	if c.current.results == nil {
		return false
	}
	ct := c.current.current_match_text()
	if ct != "" {
		all_text_before_completion := self.AllText()
		before := c.current.before_cursor[:c.current.results.CurrentWordIdx] + ct
		after := c.current.after_cursor
		self.input_state.lines = utils.Splitlines(before)
		if len(self.input_state.lines) == 0 {
			self.input_state.lines = []string{""}
		}
		self.input_state.cursor.Y = len(self.input_state.lines) - 1
		self.input_state.cursor.X = len(self.input_state.lines[self.input_state.cursor.Y])
		al := utils.Splitlines(after)
		if len(al) > 0 {
			self.input_state.lines[self.input_state.cursor.Y] += al[0]
			self.input_state.lines = append(self.input_state.lines, al[1:]...)
		}
		if c.current.num_of_matches == 1 && self.AllText() == all_text_before_completion {
			// when there is only a single match and it has already been inserted there is no point iterating over current completions
			orig := self.last_action
			self.last_action = ActionNil
			self.complete(true, 1)
			self.last_action = orig
		}
	}
	if repeat_count > 0 {
		self.complete(forwards, repeat_count)
	}
	return true
}

func (self *Readline) screen_lines_for_match_group_with_descriptions(g *cli.MatchGroup, lines []string) []string {
	maxw := 0
	for _, m := range g.Matches {
		l := wcswidth.Stringwidth(m.Word)
		if l > 16 {
			maxw = 16
			break
		}
		if l > maxw {
			maxw = l
		}
	}
	for _, m := range g.Matches {
		lines = append(lines, utils.Splitlines(m.FormatForCompletionList(maxw, self.fmt_ctx, self.screen_width))...)
	}
	return lines
}

type cell struct {
	text   string
	length int
}

func (self cell) whitespace(desired_length int) string {
	return strings.Repeat(" ", max(0, desired_length-self.length))
}

type column struct {
	cells   []cell
	length  int
	is_last bool
}

func (self *column) update_length() int {
	self.length = 0
	for _, c := range self.cells {
		if c.length > self.length {
			self.length = c.length
		}
	}
	if !self.is_last {
		self.length++
	}
	return self.length
}

func layout_words_in_table(words []string, lengths map[string]int, num_cols int) ([]column, int) {
	cols := make([]column, num_cols)
	for i, col := range cols {
		col.cells = make([]cell, 0, len(words))
		if i == len(cols)-1 {
			col.is_last = true
		}
	}
	c := 0
	for _, word := range words {
		cols[c].cells = append(cols[c].cells, cell{word, lengths[word]})
		c++
		if c >= num_cols {
			c = 0
		}
	}
	total_length := 0
	for i := range cols {
		if d := len(cols[0].cells) - len(cols[i].cells); d > 0 {
			cols[i].cells = append(cols[i].cells, make([]cell, d)...)
		}
		total_length += cols[i].update_length()
	}
	return cols, total_length
}

func (self *Readline) screen_lines_for_match_group_without_descriptions(g *cli.MatchGroup, lines []string) []string {
	words := make([]string, len(g.Matches))
	lengths := make(map[string]int, len(words))
	max_length := 0
	for i, m := range g.Matches {
		words[i] = m.Word
		l := wcswidth.Stringwidth(words[i])
		lengths[words[i]] = l
		if l > max_length {
			max_length = l
		}
	}
	var ans []column
	ncols := max(1, self.screen_width/(max_length+1))
	for {
		cols, total_length := layout_words_in_table(words, lengths, ncols)
		if total_length > self.screen_width {
			break
		}
		ans = cols
		ncols++
	}
	if ans == nil {
		for _, w := range words {
			if lengths[w] > self.screen_width {
				lines = append(lines, wcswidth.TruncateToVisualLength(w, self.screen_width))
			} else {
				lines = append(lines, w)
			}
		}
	} else {
		for r := 0; r < len(ans[0].cells); r++ {
			w := strings.Builder{}
			w.Grow(self.screen_width)
			for c := 0; c < len(ans); c++ {
				cell := ans[c].cells[r]
				w.WriteString(cell.text)
				if !ans[c].is_last {
					w.WriteString(cell.whitespace(ans[c].length))
				}
			}
			lines = append(lines, w.String())
		}
	}
	return lines
}

func (self *Readline) completion_screen_lines() ([]string, bool) {
	if self.completions.current.results == nil || self.completions.current.num_of_matches < 2 {
		return []string{}, false
	}
	if len(self.completions.current.rendered_lines) > 0 && self.completions.current.rendered_at_screen_width == self.screen_width {
		return self.completions.current.rendered_lines, true
	}
	lines := make([]string, 0, self.completions.current.num_of_matches)
	for _, g := range self.completions.current.results.Groups {
		if len(g.Matches) == 0 {
			continue
		}
		if g.Title != "" {
			lines = append(lines, self.fmt_ctx.Title(g.Title))
		}
		has_descriptions := false
		for _, m := range g.Matches {
			if m.Description != "" {
				has_descriptions = true
				break
			}
		}
		if has_descriptions {
			lines = self.screen_lines_for_match_group_with_descriptions(g, lines)
		} else {
			lines = self.screen_lines_for_match_group_without_descriptions(g, lines)
		}
	}
	self.completions.current.rendered_lines = lines
	self.completions.current.rendered_at_screen_width = self.screen_width
	return lines, false
}
