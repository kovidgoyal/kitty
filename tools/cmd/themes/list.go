// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"fmt"

	"kitty/tools/themes"
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

func (self *ThemesList) UpdateThemes(themes *themes.Themes) {
	self.themes, self.all_themes = themes, themes
	if self.current_search != "" {
		self.themes = self.all_themes.Copy()
	} else {
	}
}
