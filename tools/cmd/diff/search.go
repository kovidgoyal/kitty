// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"regexp"
	"strings"
	"sync"

	"kitty/tools/tui/sgr"
	"kitty/tools/utils"
	"kitty/tools/utils/images"
	"kitty/tools/wcswidth"

	"golang.org/x/exp/slices"
)

var _ = fmt.Print

type Search struct {
	pat     *regexp.Regexp
	matches map[ScrollPos][]*sgr.Span
}

func (self *Search) Len() int { return len(self.matches) }

func (self *Search) find_matches_in_lines(clean_lines []string, origin int, send_result func(screen_line, offset, size int)) {
	lengths := utils.Map(func(x string) int { return len(x) }, clean_lines)
	offsets := make([]int, len(clean_lines))
	for i := range clean_lines {
		if i > 0 {
			offsets[i] = offsets[i-1] + lengths[i-1]
		}
	}
	matches := self.pat.FindAllStringIndex(strings.Join(clean_lines, ""), -1)
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
					offset := 0
					if i == start_line {
						offset = start - offsets[i]
					}
					size := len(clean_lines[i]) - offset
					if i == end_line {
						size = (end - offsets[i]) - offset
					}
					send_result(i, origin+offset, size)
				}
			}
		}
	}

}

func (self *Search) find_matches_in_line(line *LogicalLine, margin_size, cols int, send_result func(screen_line, offset, size int)) {
	half_width := cols / 2
	right_offset := half_width + margin_size
	left_clean_lines, right_clean_lines := make([]string, len(line.screen_lines)), make([]string, len(line.screen_lines))
	lt := line.line_type
	for i, line := range line.screen_lines {
		line = wcswidth.StripEscapeCodes(line)
		if lt == HUNK_TITLE_LINE || lt == FULL_TITLE_LINE {
			if len(line) > margin_size {
				left_clean_lines[i] = line[margin_size:]
			}
		} else {
			if len(line) >= half_width+1 {
				left_clean_lines[i] = line[margin_size:half_width]
			}
			if len(line) > right_offset {
				right_clean_lines[i] = line[right_offset:]
			}
		}
	}
	self.find_matches_in_lines(left_clean_lines, margin_size, send_result)
	self.find_matches_in_lines(right_clean_lines, right_offset, send_result)
}

func (self *Search) Has(pos ScrollPos) bool {
	return len(self.matches[pos]) > 0
}

func (self *Search) search(logical_lines *LogicalLines) {
	margin_size := logical_lines.margin_size
	cols := logical_lines.columns
	self.matches = make(map[ScrollPos][]*sgr.Span)
	ctx := images.Context{}
	mutex := sync.Mutex{}
	s := sgr.NewSpan(0, 0)
	s.SetForeground(conf.Search_fg).SetBackground(conf.Search_bg)
	ctx.Parallel(0, logical_lines.Len(), func(nums <-chan int) {
		for i := range nums {
			line := logical_lines.At(i)
			if line.line_type == EMPTY_LINE || line.line_type == IMAGE_LINE {
				continue
			}
			self.find_matches_in_line(line, margin_size, cols, func(screen_line, offset, size int) {
				mutex.Lock()
				defer mutex.Unlock()
				sn := *s
				sn.Offset, sn.Size = offset, size
				pos := ScrollPos{i, screen_line}
				self.matches[pos] = append(self.matches[pos], &sn)
			})
		}
	})
	for _, spans := range self.matches {
		slices.SortFunc(spans, func(a, b *sgr.Span) bool { return a.Offset < b.Offset })
	}
}

func (self *Search) markup_line(line string, pos ScrollPos) string {
	spans := self.matches[pos]
	if spans == nil {
		return line
	}
	return sgr.InsertFormatting(line, spans...)
}

func do_search(pat *regexp.Regexp, logical_lines *LogicalLines) *Search {
	ans := &Search{pat: pat, matches: make(map[ScrollPos][]*sgr.Span)}
	ans.search(logical_lines)
	return ans
}
