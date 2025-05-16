package choose_fonts

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/subseq"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type FamilyList struct {
	families, all_families []string
	current_search         string
	display_strings        []string
	widths                 []int
	max_width, current_idx int
}

func (self *FamilyList) Len() int {
	return len(self.families)
}

func (self *FamilyList) Select(family string) bool {
	for idx, q := range self.families {
		if q == family {
			self.current_idx = idx
			return true
		}
	}
	return false
}

func (self *FamilyList) Next(delta int, allow_wrapping bool) bool {
	l := func() int { return self.Len() }
	if l() == 0 {
		return false
	}
	idx := self.current_idx + delta
	if !allow_wrapping && (idx < 0 || idx > l()) {
		return false
	}
	for idx < 0 {
		idx += l()
	}
	self.current_idx = idx % l()
	return true
}

func limit_lengths(text string) string {
	t, _ := wcswidth.TruncateToVisualLengthWithWidth(text, 31)
	if len(t) >= len(text) {
		return text
	}
	return t + "…"
}

func match(expression string, items []string) []*subseq.Match {
	matches := subseq.ScoreItems(expression, items, subseq.Options{Level1: " "})
	matches = utils.StableSort(matches, func(a, b *subseq.Match) int {
		if b.Score < a.Score {
			return -1
		}
		if b.Score > a.Score {
			return 1
		}
		return 0
	})
	return matches
}

const (
	MARK_BEFORE = "\033[33m"
	MARK_AFTER  = "\033[39m"
)

func apply_search(families []string, expression string, marks ...string) (matched_families []string, display_strings []string) {
	mark_before, mark_after := MARK_BEFORE, MARK_AFTER
	if len(marks) == 2 {
		mark_before, mark_after = marks[0], marks[1]
	}
	results := utils.Filter(match(expression, families), func(x *subseq.Match) bool { return x.Score > 0 })
	matched_families = make([]string, 0, len(results))
	display_strings = make([]string, 0, len(results))
	for _, m := range results {
		text := m.Text
		positions := m.Positions
		for i := len(positions) - 1; i >= 0; i-- {
			p := positions[i]
			text = text[:p] + mark_before + text[p:p+1] + mark_after + text[p+1:]
		}
		display_strings = append(display_strings, text)
		matched_families = append(matched_families, m.Text)
	}
	return
}

func make_family_names_clickable(family string) string {
	id := wcswidth.StripEscapeCodes(family)
	return tui.InternalHyperlink(family, "family-chosen:"+id)
}

func (self *FamilyList) UpdateFamilies(families []string) {
	self.families, self.all_families = families, families
	if self.current_search != "" {
		self.families, self.display_strings = apply_search(self.all_families, self.current_search)
		self.display_strings = utils.Map(limit_lengths, self.display_strings)
	} else {
		self.display_strings = utils.Map(limit_lengths, families)
	}
	self.display_strings = utils.Map(make_family_names_clickable, self.display_strings)
	self.widths = utils.Map(wcswidth.Stringwidth, self.display_strings)
	self.max_width = utils.Max(0, self.widths...)
	self.current_idx = 0
}

func (self *FamilyList) UpdateSearch(query string) bool {
	if query == self.current_search || len(self.all_families) == 0 {
		return false
	}
	self.current_search = query
	self.UpdateFamilies(self.all_families)
	return true
}

type Line struct {
	text       string
	width      int
	is_current bool
}

func (self *FamilyList) Lines(num_rows int) []Line {
	if num_rows < 1 {
		return nil
	}
	ans := make([]Line, 0, len(self.display_strings))
	before_num := utils.Min(self.current_idx, num_rows-1)
	start := self.current_idx - before_num
	for i := start; i < utils.Min(start+num_rows, len(self.display_strings)); i++ {
		ans = append(ans, Line{self.display_strings[i], self.widths[i], i == self.current_idx})
	}
	return ans
}

func (self *FamilyList) SelectFamily(family string) bool {
	for i, f := range self.families {
		if f == family {
			self.current_idx = i
			return true
		}
	}
	return false
}

func (self *FamilyList) CurrentFamily() string {
	if self.current_idx >= 0 && self.current_idx < len(self.families) {
		return self.families[self.current_idx]
	}
	return ""
}
