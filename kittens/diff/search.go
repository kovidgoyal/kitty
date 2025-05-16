// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"regexp"
	"slices"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type Search struct {
	pat     *regexp.Regexp
	matches map[ScrollPos][]Span
}

func (self *Search) Len() int { return len(self.matches) }

func (self *Search) find_matches_in_lines(clean_lines []string, origin int, send_result func(screen_line, offset, size int)) {
	lengths := utils.Map(func(x string) int { return len(x) }, clean_lines)
	offsets := make([]int, len(clean_lines))
	cell_lengths := utils.Map(wcswidth.Stringwidth, clean_lines)
	cell_offsets := make([]int, len(clean_lines))
	for i := range clean_lines {
		if i > 0 {
			offsets[i] = offsets[i-1] + lengths[i-1]
			cell_offsets[i] = cell_offsets[i-1] + cell_lengths[i-1]
		}
	}
	joined_text := strings.Join(clean_lines, "")
	matches := self.pat.FindAllStringIndex(joined_text, -1)
	pos := 0

	find_pos := func(start int) int {
		for i := pos; i < len(clean_lines); i++ {
			if start < offsets[i]+lengths[i] {
				pos = i
				return pos
			}

		}
		return -1
	}
	for _, m := range matches {
		start, end := m[0], m[1]
		total_size := end - start
		if total_size < 1 {
			continue
		}
		start_line := find_pos(start)
		if start_line > -1 {
			end_line := find_pos(end)
			if end_line > -1 {
				for i := start_line; i <= end_line; i++ {
					cell_start := 0
					if i == start_line {
						byte_offset := start - offsets[i]
						cell_start = wcswidth.Stringwidth(clean_lines[i][:byte_offset])
					}
					cell_end := cell_lengths[i]
					if i == end_line {
						byte_offset := end - offsets[i]
						cell_end = wcswidth.Stringwidth(clean_lines[i][:byte_offset])
					}
					send_result(i, origin+cell_start, cell_end-cell_start)
				}
			}
		}
	}

}

func (self *Search) find_matches_in_line(line *LogicalLine, margin_size, cols int, send_result func(screen_line, offset, size int)) {
	half_width := cols / 2
	right_offset := half_width + margin_size
	left_clean_lines, right_clean_lines := make([]string, len(line.screen_lines)), make([]string, len(line.screen_lines))
	for i, sl := range line.screen_lines {
		if line.is_full_width {
			left_clean_lines[i] = wcswidth.StripEscapeCodes(sl.left.marked_up_text)
		} else {
			left_clean_lines[i] = wcswidth.StripEscapeCodes(sl.left.marked_up_text)
			right_clean_lines[i] = wcswidth.StripEscapeCodes(sl.right.marked_up_text)
		}
	}
	self.find_matches_in_lines(left_clean_lines, margin_size, send_result)
	self.find_matches_in_lines(right_clean_lines, right_offset, send_result)
}

func (self *Search) Has(pos ScrollPos) bool {
	return len(self.matches[pos]) > 0
}

type Span struct{ start, end int }

func (self *Search) search(logical_lines *LogicalLines) {
	margin_size := logical_lines.margin_size
	cols := logical_lines.columns
	self.matches = make(map[ScrollPos][]Span)
	ctx := images.Context{}
	mutex := sync.Mutex{}
	ctx.Parallel(0, logical_lines.Len(), func(nums <-chan int) {
		for i := range nums {
			line := logical_lines.At(i)
			if line.line_type == EMPTY_LINE || line.line_type == IMAGE_LINE {
				continue
			}
			self.find_matches_in_line(line, margin_size, cols, func(screen_line, offset, size int) {
				if size > 0 {
					mutex.Lock()
					defer mutex.Unlock()
					pos := ScrollPos{i, screen_line}
					self.matches[pos] = append(self.matches[pos], Span{offset, offset + size - 1})
				}
			})
		}
	})
	for _, spans := range self.matches {
		slices.SortFunc(spans, func(a, b Span) int { return a.start - b.start })
	}
}

func (self *Search) markup_line(pos ScrollPos, y int) string {
	spans := self.matches[pos]
	if spans == nil {
		return ""
	}
	sgr := format_as_sgr.search[2:]
	sgr = sgr[:len(sgr)-1]
	ans := make([]byte, 0, 32)
	for _, span := range spans {
		ans = append(ans, tui.FormatPartOfLine(sgr, span.start, span.end, y)...)
	}
	return utils.UnsafeBytesToString(ans)
}

func do_search(pat *regexp.Regexp, logical_lines *LogicalLines) *Search {
	ans := &Search{pat: pat, matches: make(map[ScrollPos][]Span)}
	ans.search(logical_lines)
	return ans
}
