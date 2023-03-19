// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"kitty/tools/utils"
	"kitty/tools/utils/style"
	"kitty/tools/wcswidth"
	"strconv"
	"strings"
)

var _ = fmt.Print

type LineType int

const (
	TITLE_LINE LineType = iota
	CHANGE_LINE
	IMAGE_LINE
)

type Reference struct {
	path    string
	linenum int
}

type LogicalLine struct {
	src                  Reference
	line_type            LineType
	margin_size, columns int
	screen_lines         []string
}

func fit_in(text string, count int) string {
	truncated := wcswidth.TruncateToVisualLength(text, count)
	if len(truncated) >= len(text) {
		return text
	}
	if count > 1 {
		truncated = wcswidth.TruncateToVisualLength(text, count-1)
	}
	return truncated + `…`
}

func fill_in(text string, sz int) string {
	w := wcswidth.Stringwidth(text)
	if w < sz {
		text += strings.Repeat(` `, (sz - w))
	}
	return text
}

func place_in(text string, sz int) string {
	return fill_in(fit_in(text, sz), sz)
}

var title_format, text_format, margin_format, added_format, removed_format, added_margin_format, removed_margin_format, filler_format, margin_filler_format, hunk_margin_format, hunk_format func(...any) string

func create_formatters() {
	ctx := style.Context{AllowEscapeCodes: true}
	text_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Background.AsRGBSharp()))
	filler_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Filler_bg.AsRGBSharp()))
	if conf.Margin_filler_bg.IsNull {
		margin_filler_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Filler_bg.AsRGBSharp()))
	} else {
		margin_filler_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Margin_filler_bg.Color.AsRGBSharp()))
	}
	added_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Added_bg.AsRGBSharp()))
	added_margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Added_margin_bg.AsRGBSharp()))
	removed_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Removed_bg.AsRGBSharp()))
	removed_margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Removed_margin_bg.AsRGBSharp()))
	title_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Title_fg.AsRGBSharp(), conf.Title_bg.AsRGBSharp()))
	margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Margin_bg.AsRGBSharp()))
	hunk_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Hunk_bg.AsRGBSharp()))
	hunk_margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Hunk_margin_bg.AsRGBSharp()))
}

func title_lines(left_path, right_path string, columns, margin_size int, ans []*LogicalLine) []*LogicalLine {
	left_name, right_name := path_name_map[left_path], path_name_map[right_path]
	name := ""
	m := strings.Repeat(` `, margin_size)
	if right_name != "" && right_name != left_name {
		n1 := fit_in(m+sanitize(left_name), columns/2-margin_size)
		n1 = place_in(n1, columns/2)
		n2 := fit_in(m+sanitize(right_name), columns/2-margin_size)
		n2 = place_in(n2, columns/2)
		name = n1 + n2
	} else {
		name = place_in(m+sanitize(left_name), columns)
	}
	ll := LogicalLine{columns: columns, margin_size: margin_size, line_type: TITLE_LINE, src: Reference{path: left_path, linenum: 0}}
	l1 := ll
	l1.screen_lines = []string{title_format(name)}
	l2 := ll
	l2.screen_lines = []string{title_format(name)}
	return append(ans, &l1, &l2)
}

type LogicalLines struct {
	lines                []*LogicalLine
	margin_size, columns int
}

func render(collection *Collection, diff_map map[string]*Patch, columns int) (*LogicalLines, error) {
	largest_line_number := 0
	collection.Apply(func(path, typ, changed_path string) error {
		if typ == "diff" {
			patch := diff_map[path]
			if patch != nil {
				largest_line_number = utils.Max(largest_line_number, patch.largest_line_number)
			}
		}
		return nil
	})
	margin_size := utils.Max(3, len(strconv.Itoa(largest_line_number))+1)
	ans := make([]*LogicalLine, 0, 1024)
	err := collection.Apply(func(path, item_type, changed_path string) error {
		ans = title_lines(path, changed_path, columns, margin_size, ans)

		is_binary := !is_path_text(path)
		if !is_binary && item_type == `diff` && !is_path_text(changed_path) {
			is_binary = true
		}
		is_img := is_binary && is_image(path) || (item_type == `diff` && is_image(changed_path))
		_ = is_img

		return nil
	})
	if err != nil {
		return nil, err
	}

	return &LogicalLines{lines: ans[:len(ans)-1], margin_size: margin_size, columns: columns}, nil
}

func (self *LogicalLines) num_of_screen_lines() (ans int) {
	for _, l := range self.lines {
		ans += len(l.screen_lines)
	}
	return
}
