// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package unicode_input

import (
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/unicode_names"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

func resolved_char(ch rune, emoji_variation string) string {
	ans := string(ch)
	if wcswidth.IsEmojiPresentationBase(ch) {
		switch emoji_variation {
		case "text":
			ans += "\ufe0e"
		case "graphic":
			ans += "\ufe0f"
		}
	}
	return ans

}

func decode_hint(text string) int {
	x, err := strconv.ParseInt(text, INDEX_BASE, 0)
	if err != nil || x < 0 {
		return -1
	}
	return int(x)
}

func encode_hint(num int) string {
	return strconv.FormatUint(uint64(num), INDEX_BASE)
}

func ljust(s string, sz int) string {
	x := wcswidth.Stringwidth(s)
	if x < sz {
		s += strings.Repeat(" ", sz-x)
	}
	return s
}

type scroll_data struct {
	num_items_per_page int
	scroll_rows        int
}

type table struct {
	emoji_variation      string
	layout_dirty         bool
	last_rows, last_cols int
	codepoints           []rune
	current_idx          int
	scroll_data          scroll_data
	text                 string
	num_cols, num_rows   int
	mode                 Mode

	green, reversed, intense_gray func(...any) string
}

func (self *table) initialize(emoji_variation string, ctx style.Context) {
	self.emoji_variation = emoji_variation
	self.layout_dirty = true
	self.last_cols, self.last_rows = -1, -1
	self.green = ctx.SprintFunc("fg=green")
	self.reversed = ctx.SprintFunc("reverse=true")
	self.intense_gray = ctx.SprintFunc("fg=intense-gray")
}

func (self *table) current_codepoint() rune {
	if len(self.codepoints) > 0 {
		return self.codepoints[self.current_idx]
	}
	return InvalidChar
}

func (self *table) set_codepoints(codepoints []rune, mode Mode, current_idx int) {
	delta := len(codepoints) - len(self.codepoints)
	self.codepoints = codepoints
	if self.codepoints != nil && mode != FAVORITES && mode != HEX {
		slices.Sort(self.codepoints)
	}
	self.mode = mode
	self.layout_dirty = true
	if current_idx > -1 && current_idx < len(self.codepoints) {
		self.current_idx = current_idx
	}
	if self.current_idx >= len(self.codepoints) {
		self.current_idx = 0
	}
	if delta != 0 {
		self.scroll_data = scroll_data{}
	}
}

func (self *table) codepoint_at_hint(hint string) rune {
	idx := decode_hint(hint)
	if idx >= 0 && idx < len(self.codepoints) {
		return self.codepoints[idx]
	}
	return InvalidChar
}

type cell_data struct {
	idx, ch, desc string
}

func title(x string) string {
	if len(x) > 1 {
		x = strings.ToUpper(x[:1]) + x[1:]
	}
	return x
}

func (self *table) layout(rows, cols int) string {
	if !self.layout_dirty && self.last_cols == cols && self.last_rows == rows {
		return self.text
	}
	self.last_cols, self.last_rows = cols, rows
	self.layout_dirty = false
	var as_parts func(int, rune) cell_data
	var cell func(int, cell_data)
	var idx_size, space_for_desc int
	output := strings.Builder{}
	output.Grow(4096)
	switch self.mode {
	case NAME:
		as_parts = func(i int, codepoint rune) cell_data {
			return cell_data{idx: ljust(encode_hint(i), idx_size), ch: resolved_char(codepoint, self.emoji_variation), desc: title(unicode_names.NameForCodePoint(codepoint))}
		}

		cell = func(i int, cd cell_data) {
			is_current := i == self.current_idx
			text := self.green(cd.idx) + " " + cd.ch + " "
			w := wcswidth.Stringwidth(cd.ch)
			if w < 2 {
				text += strings.Repeat(" ", (2 - w))
			}
			desc_width := wcswidth.Stringwidth(cd.desc)
			if desc_width > space_for_desc {
				text += cd.desc[:space_for_desc-1] + "…"
			} else {
				text += cd.desc
				extra := space_for_desc - desc_width
				if extra > 0 {
					text += strings.Repeat(" ", extra)
				}
			}
			if is_current {
				text = self.reversed(text)
			}
			output.WriteString(text)
		}
	default:
		as_parts = func(i int, codepoint rune) cell_data {
			return cell_data{idx: ljust(encode_hint(i), idx_size), ch: resolved_char(codepoint, self.emoji_variation)}
		}

		cell = func(i int, cd cell_data) {
			output.WriteString(self.green(cd.idx))
			output.WriteString(" ")
			output.WriteString(self.intense_gray(cd.ch))
			w := wcswidth.Stringwidth(cd.ch)
			if w < 2 {
				output.WriteString(strings.Repeat(" ", (2 - w)))
			}
		}
	}

	num := len(self.codepoints)
	if num < 1 {
		self.text = ""
		self.num_cols = 0
		self.num_rows = 0
		return self.text
	}
	idx_size = len(encode_hint(num - 1))

	parts := make([]cell_data, len(self.codepoints))
	for i, ch := range self.codepoints {
		parts[i] = as_parts(i, ch)
	}
	longest := 0
	switch self.mode {
	case NAME:
		for _, p := range parts {
			longest = utils.Max(longest, idx_size+2+len(p.desc)+2)
		}
	default:
		longest = idx_size + 3
	}
	col_width := longest + 2
	col_width = utils.Min(col_width, 40)
	self.num_cols = utils.Max(cols/col_width, 1)
	if self.num_cols == 1 {
		col_width = cols
	}
	space_for_desc = col_width - 2 - idx_size - 4
	self.num_rows = rows
	rows_left := rows
	if self.scroll_data.num_items_per_page != self.num_cols*self.num_rows {
		self.update_scroll_data()
	}
	skip_scroll := self.scroll_data.scroll_rows * self.num_cols

	for i, cd := range parts {
		if skip_scroll > 0 {
			skip_scroll -= 1
			continue
		}
		cell(i, cd)
		output.WriteString("  ")
		if self.num_cols == 1 || (i > 0 && (i+1)%self.num_cols == 0) {
			rows_left -= 1
			if rows_left == 0 {
				break
			}
			output.WriteString("\r\n")
		}
	}

	self.text = output.String()
	return self.text
}

func (self *table) update_scroll_data() {
	self.scroll_data.num_items_per_page = self.num_rows * self.num_cols
	page_num := self.current_idx / self.scroll_data.num_items_per_page
	self.scroll_data.scroll_rows = self.num_rows * page_num
}

func (self *table) move_current(rows, cols int) {
	if len(self.codepoints) == 0 {
		return
	}
	if cols != 0 {
		self.current_idx = (self.current_idx + len(self.codepoints) + cols) % len(self.codepoints)
		self.layout_dirty = true
	}
	if rows != 0 {
		amt := rows * self.num_cols
		self.current_idx += amt
		self.current_idx = utils.Max(0, utils.Min(self.current_idx, len(self.codepoints)-1))
		self.layout_dirty = true
	}
	self.update_scroll_data()
}
