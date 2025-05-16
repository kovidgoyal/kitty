// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"fmt"

	"github.com/kovidgoyal/kitty/tools/themes"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type ThemesList struct {
	themes, all_themes     *themes.Themes
	current_search         string
	display_strings        []string
	widths                 []int
	max_width, current_idx int
}

func (self *ThemesList) Len() int {
	if self.themes == nil {
		return 0
	}
	return self.themes.Len()
}

func (self *ThemesList) Next(delta int, allow_wrapping bool) bool {
	if len(self.display_strings) == 0 {
		return false
	}
	idx := self.current_idx + delta
	if !allow_wrapping && (idx < 0 || idx > self.Len()) {
		return false
	}
	for idx < 0 {
		idx += self.Len()
	}
	self.current_idx = idx % self.Len()
	return true
}

func limit_lengths(text string) string {
	t, _ := wcswidth.TruncateToVisualLengthWithWidth(text, 31)
	if len(t) >= len(text) {
		return text
	}
	return t + "…"
}

func (self *ThemesList) UpdateThemes(themes *themes.Themes) {
	self.themes, self.all_themes = themes, themes
	if self.current_search != "" {
		self.themes = self.all_themes.Copy()
		self.display_strings = utils.Map(limit_lengths, self.themes.ApplySearch(self.current_search))
	} else {
		self.display_strings = utils.Map(limit_lengths, self.themes.Names())
	}
	self.widths = utils.Map(wcswidth.Stringwidth, self.display_strings)
	self.max_width = utils.Max(0, self.widths...)
	self.current_idx = 0
}

func (self *ThemesList) UpdateSearch(query string) bool {
	if query == self.current_search || self.all_themes == nil {
		return false
	}
	self.current_search = query
	self.UpdateThemes(self.all_themes)
	return true
}

type Line struct {
	text       string
	width      int
	is_current bool
}

func (self *ThemesList) Lines(num_rows int) []Line {
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

func (self *ThemesList) CurrentTheme() *themes.Theme {
	if self.themes == nil {
		return nil
	}
	return self.themes.At(self.current_idx)
}
