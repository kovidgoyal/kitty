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
	HUNK_TITLE_LINE
	IMAGE_LINE
	EMPTY_LINE
)

type Reference struct {
	path    string
	linenum int
}

type LogicalLine struct {
	src             Reference
	line_type       LineType
	screen_lines    []string
	is_change_start bool
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

var title_format, text_format, margin_format, added_format, removed_format, added_margin_format, removed_margin_format, filler_format, margin_filler_format, hunk_margin_format, hunk_format, added_center, removed_center func(...any) string

func create_formatters() {
	ctx := style.Context{AllowEscapeCodes: true}
	text_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Background.AsRGBSharp()))
	filler_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Filler_bg.AsRGBSharp()))
	if conf.Margin_filler_bg.IsSet {
		margin_filler_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Margin_filler_bg.Color.AsRGBSharp()))
	} else {
		margin_filler_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Filler_bg.AsRGBSharp()))
	}
	added_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Added_bg.AsRGBSharp()))
	added_margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Added_margin_bg.AsRGBSharp()))
	removed_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Removed_bg.AsRGBSharp()))
	removed_margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Removed_margin_bg.AsRGBSharp()))
	title_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s bold", conf.Title_fg.AsRGBSharp(), conf.Title_bg.AsRGBSharp()))
	margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Margin_bg.AsRGBSharp()))
	hunk_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Hunk_bg.AsRGBSharp()))
	hunk_margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Hunk_margin_bg.AsRGBSharp()))
	make_bracketer := func(start, end string) func(...any) string {
		s, e := ctx.SprintFunc(start), ctx.SprintFunc(end)
		end = e(" ")
		idx := strings.LastIndexByte(end, ' ')
		end = end[:idx]
		start = s(" ")
		idx = strings.LastIndexByte(start, ' ')
		start = start[:idx]

		return func(args ...any) string {
			return start + fmt.Sprint(args) + end
		}
	}
	added_center = make_bracketer("bg="+conf.Highlight_added_bg.AsRGBSharp(), "bg="+conf.Added_bg.AsRGBSharp())
	removed_center = make_bracketer("bg="+conf.Highlight_removed_bg.AsRGBSharp(), "bg="+conf.Removed_bg.AsRGBSharp())
}

func highlight_boundaries(ltype, text string) string {
	switch ltype {
	case "add":
		return added_center(text)
	case "remove":
		return removed_center(text)
	}
	return text
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
	ll := LogicalLine{line_type: TITLE_LINE, src: Reference{path: left_path, linenum: 0}}
	l1 := ll
	l1.screen_lines = []string{title_format(name)}
	l2 := ll
	l2.screen_lines = []string{title_format(strings.Repeat("━", columns+1))}
	return append(ans, &l1, &l2)
}

type LogicalLines struct {
	lines                []*LogicalLine
	margin_size, columns int
}

func image_lines(left_path, right_path string, columns, margin_size int, ans []*LogicalLine) ([]*LogicalLine, error) {
	// TODO: Implement this
	return ans, nil
}

func human_readable(size int) string {
	divisor, suffix := 1, "B"
	for i, candidate := range []string{"B", "KB", "MB", "GB", "TB", "PB", "EB"} {
		if size < (1 << ((i + 1) * 10)) {
			divisor, suffix = (1 << (i * 10)), candidate
			break
		}
	}
	fs := float64(size) / float64(divisor)
	s := strconv.FormatFloat(fs, 'f', 2, 64)
	if idx := strings.Index(s, "."); idx > -1 {
		s = s[:idx+2]
	}
	if strings.HasSuffix(s, ".0") || strings.HasSuffix(s, ".00") {
		idx := strings.IndexByte(s, '.')
		s = s[:idx]
	}
	return s + " " + suffix
}

func render_diff_line(number, text, ltype string, margin_size int, available_cols int) string {
	m, c := margin_format, text_format
	switch ltype {
	case `filler`:
		m = margin_filler_format
		c = filler_format
	case `remove`:
		m = removed_margin_format
		c = removed_format
	case `add`:
		m = added_margin_format
		c = added_format
	}
	margin := m(place_in(number, margin_size))
	content := c(fill_in(text, available_cols))
	return margin + content
}

func binary_lines(left_path, right_path string, columns, margin_size int, ans []*LogicalLine) (ans2 []*LogicalLine, err error) {
	available_cols := columns/2 - margin_size
	fl := func(path string, formatter func(...any) string) string {
		if err == nil {
			var data string
			data, err = data_for_path(path)
			text := fmt.Sprintf("Binary file: %s", human_readable(len(data)))
			text = place_in(text, available_cols)
			return margin_format(strings.Repeat(` `, margin_size)) + formatter(text)
		}
		return ""
	}
	line := ""
	if left_path == "" {
		filler := render_diff_line(``, ``, `filler`, margin_size, available_cols)
		line = filler + fl(right_path, added_format)
	} else if right_path == "" {
		filler := render_diff_line(``, ``, `filler`, margin_size, available_cols)
		line = fl(left_path, removed_format) + filler
	} else {
		line = fl(left_path, removed_format) + fl(right_path, added_format)
	}
	ll := LogicalLine{is_change_start: true, line_type: CHANGE_LINE, src: Reference{path: left_path, linenum: 0}, screen_lines: []string{line}}
	if left_path == "" {
		ll.src.path = right_path
	}
	return append(ans, &ll), err
}

type DiffData struct {
	left_path, right_path       string
	available_cols, margin_size int

	left_lines, right_lines                          []string
	filler_line, left_filler_line, right_filler_line string
}

func hunk_title(hunk_num int, hunk *Hunk, margin_size, available_cols int) string {
	m := hunk_margin_format(strings.Repeat(" ", margin_size))
	t := fmt.Sprintf("@@ %d,%d +%d,%d @@ %s", hunk.left_start+1, hunk.left_count, hunk.right_start+1, hunk.right_count, hunk.title)
	return m + hunk_format(place_in(t, available_cols))
}

func lines_for_context_chunk(data *DiffData, hunk_num int, chunk *Chunk, chunk_num int, ans []*LogicalLine) []*LogicalLine {
	for i := 0; i < chunk.left_count; i++ {
		left_line_number := chunk.left_start + i
		right_line_number := chunk.right_start + i
		ll := LogicalLine{line_type: CHANGE_LINE, src: Reference{path: data.left_path, linenum: left_line_number}}
		left_line_number_s := strconv.Itoa(left_line_number + 1)
		right_line_number_s := strconv.Itoa(right_line_number + 1)
		for _, text := range splitlines(data.left_lines[left_line_number], data.available_cols) {
			line := render_diff_line(left_line_number_s, text, `context`, data.margin_size, data.available_cols)
			if right_line_number_s == left_line_number_s {
				line += line
			} else {
				line += render_diff_line(right_line_number_s, text, `context`, data.margin_size, data.available_cols)
			}
			ll.screen_lines = append(ll.screen_lines, line)
			left_line_number_s, right_line_number_s = "", ""
		}
		ans = append(ans, &ll)
	}
	return ans
}

func splitlines(text string, width int) []string {
	return style.WrapTextAsLines(text, "", width)
}

func render_half_line(line_number int, line, ltype string, margin_size, available_cols int, center Center, ans []string) []string {
	if center.prefix_count > 0 {
		line_sz := len(line)
		if center.prefix_count+center.suffix_count < line_sz {
			end := len(line) - center.suffix_count
			line = line[:center.prefix_count] + highlight_boundaries(ltype, line[center.prefix_count:end]) + line[end:]
		}
	}
	lnum := strconv.Itoa(line_number + 1)
	for _, sc := range splitlines(line, available_cols) {
		ans = append(ans, render_diff_line(lnum, sc, ltype, margin_size, available_cols))
		lnum = ""
	}
	return ans
}

func lines_for_diff_chunk(data *DiffData, hunk_num int, chunk *Chunk, chunk_num int, ans []*LogicalLine) []*LogicalLine {
	common := utils.Min(chunk.left_count, chunk.right_count)
	ll, rl := make([]string, 0, 32), make([]string, 0, 32)
	for i := 0; i < utils.Max(chunk.left_count, chunk.right_count); i++ {
		ll, rl = ll[:0], rl[:0]
		ref_ln, ref_path := 0, ""
		var center Center
		if i < len(chunk.centers) {
			center = chunk.centers[i]
		}
		if i < chunk.left_count {
			ref_path = data.left_path
			ref_ln = chunk.left_start + i
			ll = render_half_line(ref_ln, data.left_lines[ref_ln], "remove", data.margin_size, data.available_cols, center, ll)
		}

		if i < chunk.right_count {
			ref_path = data.right_path
			ref_ln = chunk.right_start + i
			rl = render_half_line(ref_ln, data.right_lines[ref_ln], "add", data.margin_size, data.available_cols, center, rl)
		}

		if i < common {
			extra := len(ll) - len(rl)
			if extra < 0 {
				ll = append(ll, utils.Repeat(data.left_filler_line, -extra)...)
			} else if extra > 0 {
				rl = append(rl, utils.Repeat(data.right_filler_line, extra)...)
			}
		} else {
			if len(ll) > 0 {
				rl = append(rl, utils.Repeat(data.filler_line, len(ll))...)
			} else if len(rl) > 0 {
				ll = append(ll, utils.Repeat(data.filler_line, len(rl))...)
			}
		}
		logline := LogicalLine{line_type: CHANGE_LINE, src: Reference{path: ref_path, linenum: ref_ln}, is_change_start: i == 0}
		for l := 0; l < len(ll); l++ {
			logline.screen_lines = append(logline.screen_lines, ll[l]+rl[l])
		}
		ans = append(ans, &logline)
	}
	return ans
}

func lines_for_diff(left_path string, right_path string, patch *Patch, columns, margin_size int, ans []*LogicalLine) (result []*LogicalLine, err error) {
	available_cols := columns/2 - margin_size
	data := DiffData{left_path: left_path, right_path: right_path, available_cols: available_cols, margin_size: margin_size}
	if left_path != "" {
		data.left_lines, err = lines_for_path(left_path)
		if err != nil {
			return
		}
	}
	if right_path != "" {
		data.right_lines, err = lines_for_path(right_path)
		if err != nil {
			return
		}
	}
	data.filler_line = render_diff_line("", "", "filler", margin_size, available_cols)
	data.left_filler_line = render_diff_line("", "", "remove", margin_size, available_cols)
	data.right_filler_line = render_diff_line("", "", "add", margin_size, available_cols)

	ht := LogicalLine{line_type: HUNK_TITLE_LINE, src: Reference{path: left_path}}
	for hunk_num, hunk := range patch.all_hunks {
		htl := ht
		htl.src.linenum = hunk.left_start
		htl.screen_lines = []string{hunk_title(hunk_num, hunk, margin_size, columns-margin_size)}
		ans = append(ans, &htl)
		for cnum, chunk := range hunk.chunks {
			if chunk.is_context {
				ans = lines_for_context_chunk(&data, hunk_num, chunk, cnum, ans)
			} else {
				ans = lines_for_diff_chunk(&data, hunk_num, chunk, cnum, ans)
			}
		}
	}
	return ans, nil
}

func all_lines(path string, columns, margin_size int, is_add bool, ans []*LogicalLine) ([]*LogicalLine, error) {
	available_cols := columns/2 - margin_size
	ltype := `add`
	if !is_add {
		ltype = `remove`
	}
	lines, err := lines_for_path(path)
	if err != nil {
		return nil, err
	}
	filler := render_diff_line(``, ``, `filler`, margin_size, available_cols)
	msg_written := false

	ll := LogicalLine{src: Reference{path: path}, line_type: CHANGE_LINE}
	for line_number, line := range lines {
		hlines := make([]string, 0, 8)
		hlines = render_half_line(line_number, line, ltype, margin_size, available_cols, Center{}, hlines)
		l := ll
		l.src.linenum = line_number
		l.is_change_start = line_number == 0
		for _, hl := range hlines {
			empty := filler
			if !msg_written {
				msg_written = true
				msg := `This file was added`
				if !is_add {
					msg = `This file was removed`
				}
				empty = render_diff_line(``, msg, `filler`, margin_size, available_cols)
			}
			var text string
			if is_add {
				text = empty + hl
			} else {
				text = hl + empty
			}
			l.screen_lines = append(l.screen_lines, text)
		}
		ans = append(ans, &l)
	}
	return ans, nil
}

func rename_lines(path, other_path string, columns, margin_size int, ans []*LogicalLine) ([]*LogicalLine, error) {
	m := strings.Repeat(" ", margin_size)
	ll := LogicalLine{src: Reference{path: path, linenum: 0}, line_type: CHANGE_LINE, is_change_start: true}
	for _, line := range splitlines(fmt.Sprintf(`The file %s was renamed to %s`, sanitize(path_name_map[path]), sanitize(path_name_map[other_path])), columns-margin_size) {
		ll.screen_lines = append(ll.screen_lines, m+line)
	}
	return append(ans, &ll), nil
}

func render(collection *Collection, diff_map map[string]*Patch, columns int) (result *LogicalLines, err error) {
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
	empty_line := LogicalLine{line_type: EMPTY_LINE}
	err = collection.Apply(func(path, item_type, changed_path string) error {
		ans = title_lines(path, changed_path, columns, margin_size, ans)
		defer func() {
			el := empty_line
			ans = append(ans, &el)
		}()

		is_binary := !is_path_text(path)
		if !is_binary && item_type == `diff` && !is_path_text(changed_path) {
			is_binary = true
		}
		is_img := is_binary && is_image(path) || (item_type == `diff` && is_image(changed_path))
		_ = is_img
		switch item_type {
		case "diff":
			if is_binary {
				if is_img {
					ans, err = image_lines(path, changed_path, columns, margin_size, ans)
				} else {
					ans, err = binary_lines(path, changed_path, columns, margin_size, ans)
				}
			} else {
				ans, err = lines_for_diff(path, changed_path, diff_map[path], columns, margin_size, ans)
			}
			if err != nil {
				return err
			}
		case "add":
			if is_binary {
				if is_img {
					ans, err = image_lines("", path, columns, margin_size, ans)
				} else {
					ans, err = binary_lines("", path, columns, margin_size, ans)
				}
			} else {
				ans, err = all_lines(path, columns, margin_size, true, ans)
			}
			if err != nil {
				return err
			}
		case "removal":
			if is_binary {
				if is_img {
					ans, err = image_lines(path, "", columns, margin_size, ans)
				} else {
					ans, err = binary_lines(path, "", columns, margin_size, ans)
				}
			} else {
				ans, err = all_lines(path, columns, margin_size, false, ans)
			}
			if err != nil {
				return err
			}
		case "rename":
			ans, err = rename_lines(path, changed_path, columns, margin_size, ans)
			if err != nil {
				return err
			}
		default:
			return fmt.Errorf("Unknown change type: %#v", item_type)
		}
		return nil
	})
	return &LogicalLines{lines: ans[:len(ans)-1], margin_size: margin_size, columns: columns}, err
}

func (self *LogicalLines) num_of_screen_lines() (ans int) {
	for _, l := range self.lines {
		ans += len(l.screen_lines)
	}
	return
}
