// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"

	"kitty/tools/tui/graphics"
	"kitty/tools/tui/sgr"
	"kitty/tools/utils"
	"kitty/tools/utils/style"
	"kitty/tools/wcswidth"
)

var _ = fmt.Print

type LineType int

const (
	TITLE_LINE LineType = iota
	FULL_TITLE_LINE
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
	src                     Reference
	line_type               LineType
	screen_lines            []string
	is_change_start         bool
	left_image, right_image struct {
		key   string
		count int
	}
	image_lines_offset int
}

func (self *LogicalLine) IncrementScrollPosBy(pos *ScrollPos, amt int) (delta int) {
	if len(self.screen_lines) > 0 {
		npos := utils.Max(0, utils.Min(pos.screen_line+amt, len(self.screen_lines)-1))
		delta = npos - pos.screen_line
		pos.screen_line = npos
	}
	return
}

func join_half_lines(left, right string) string {
	return left + "\x1b[m" + right
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

var title_format, text_format, margin_format, added_format, removed_format, added_margin_format, removed_margin_format, filler_format, margin_filler_format, hunk_margin_format, hunk_format, statusline_format, added_count_format, removed_count_format, message_format, selection_format func(...any) string
var selection_sgr string

func create_formatters() {
	ctx := style.Context{AllowEscapeCodes: true}
	text_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Background.AsRGBSharp()))
	filler_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Filler_bg.AsRGBSharp()))
	if conf.Margin_filler_bg.IsSet {
		margin_filler_format = ctx.SprintFunc("bg=" + conf.Margin_filler_bg.Color.AsRGBSharp())
	} else {
		margin_filler_format = ctx.SprintFunc("bg=" + conf.Filler_bg.AsRGBSharp())
	}
	added_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Added_bg.AsRGBSharp()))
	added_margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Added_margin_bg.AsRGBSharp()))
	removed_format = ctx.SprintFunc(fmt.Sprintf("bg=%s", conf.Removed_bg.AsRGBSharp()))
	removed_margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Removed_margin_bg.AsRGBSharp()))
	title_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s bold", conf.Title_fg.AsRGBSharp(), conf.Title_bg.AsRGBSharp()))
	margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Margin_bg.AsRGBSharp()))
	statusline_format = ctx.SprintFunc(fmt.Sprintf("fg=%s", conf.Margin_fg.AsRGBSharp()))
	added_count_format = ctx.SprintFunc(fmt.Sprintf("fg=%s", conf.Highlight_added_bg.AsRGBSharp()))
	removed_count_format = ctx.SprintFunc(fmt.Sprintf("fg=%s", conf.Highlight_removed_bg.AsRGBSharp()))
	hunk_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Hunk_bg.AsRGBSharp()))
	hunk_margin_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Margin_fg.AsRGBSharp(), conf.Hunk_margin_bg.AsRGBSharp()))
	message_format = ctx.SprintFunc("bold")
	if conf.Select_fg.IsSet {
		selection_format = ctx.SprintFunc(fmt.Sprintf("fg=%s bg=%s", conf.Select_fg.Color.AsRGBSharp(), conf.Select_bg.AsRGBSharp()))
	} else {
		selection_format = ctx.SprintFunc("bg=" + conf.Select_bg.AsRGBSharp())
	}
	selection_sgr, _, _ = strings.Cut(selection_format("|"), "|")
	selection_sgr = selection_sgr[2 : len(selection_sgr)-1]
}

func center_span(ltype string, offset, size int) *sgr.Span {
	ans := sgr.NewSpan(offset, size)
	switch ltype {
	case "add":
		ans.SetBackground(conf.Highlight_added_bg).SetClosingBackground(conf.Added_bg)
	case "remove":
		ans.SetBackground(conf.Highlight_removed_bg).SetClosingBackground(conf.Removed_bg)
	}
	return ans
}

func title_lines(left_path, right_path string, columns, margin_size int, ans []*LogicalLine) []*LogicalLine {
	left_name, right_name := path_name_map[left_path], path_name_map[right_path]
	name := ""
	m := strings.Repeat(` `, margin_size)
	ll := LogicalLine{line_type: TITLE_LINE, src: Reference{path: left_path, linenum: 0}}
	if right_name != "" && right_name != left_name {
		n1 := fit_in(m+sanitize(left_name), columns/2-margin_size)
		n1 = place_in(n1, columns/2)
		n2 := fit_in(m+sanitize(right_name), columns/2-margin_size)
		n2 = place_in(n2, columns/2)
		name = n1 + n2
	} else {
		name = place_in(m+sanitize(left_name), columns)
		ll.line_type = FULL_TITLE_LINE
	}
	l1 := ll
	l1.screen_lines = []string{title_format(name)}
	l2 := ll
	l2.line_type = EMPTY_LINE
	l2.screen_lines = []string{title_format(strings.Repeat("━", columns))}
	return append(ans, &l1, &l2)
}

type LogicalLines struct {
	lines                []*LogicalLine
	margin_size, columns int
}

func (self *LogicalLines) At(i int) *LogicalLine { return self.lines[i] }
func (self *LogicalLines) ScreenLineAt(pos ScrollPos) string {
	if pos.logical_line < len(self.lines) && pos.logical_line >= 0 {
		line := self.lines[pos.logical_line]
		if pos.screen_line < len(line.screen_lines) && pos.screen_line >= 0 {
			return self.lines[pos.logical_line].screen_lines[pos.screen_line]
		}
	}
	return ""
}
func (self *LogicalLines) Len() int { return len(self.lines) }

func (self *LogicalLines) NumScreenLinesTo(a ScrollPos) (ans int) {
	return self.Minus(a, ScrollPos{})
}

// a - b in terms of number of screen lines between the positions
func (self *LogicalLines) Minus(a, b ScrollPos) (delta int) {
	if a.logical_line == b.logical_line {
		return a.screen_line - b.screen_line
	}
	amt := 1
	if a.Less(b) {
		amt = -1
	} else {
		a, b = b, a
	}
	for i := a.logical_line; i < utils.Min(len(self.lines), b.logical_line+1); i++ {
		line := self.lines[i]
		switch i {
		case a.logical_line:
			delta += utils.Max(0, len(line.screen_lines)-a.screen_line)
		case b.logical_line:
			delta += b.screen_line
		default:
			delta += len(line.screen_lines)
		}
	}
	return delta * amt
}

func (self *LogicalLines) IncrementScrollPosBy(pos *ScrollPos, amt int) (delta int) {
	if pos.logical_line < 0 || pos.logical_line >= len(self.lines) || amt == 0 {
		return
	}
	one := 1
	if amt < 0 {
		one = -1
	}
	for amt != 0 {
		line := self.lines[pos.logical_line]
		d := line.IncrementScrollPosBy(pos, amt)
		if d == 0 {
			nlp := pos.logical_line + one
			if nlp < 0 || nlp >= len(self.lines) {
				break
			}
			pos.logical_line = nlp
			if one > 0 {
				pos.screen_line = 0
			} else {
				pos.screen_line = len(self.lines[nlp].screen_lines) - 1
			}
			delta += one
			amt -= one
		} else {
			amt -= d
			delta += d
		}
	}
	return
}

func human_readable(size int64) string {
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

func image_lines(left_path, right_path string, screen_size screen_size, margin_size int, image_size graphics.Size, ans []*LogicalLine) ([]*LogicalLine, error) {
	columns := screen_size.columns
	available_cols := columns/2 - margin_size
	ll, err := first_binary_line(left_path, right_path, columns, margin_size, func(path string, formatter, margin_formatter formatter) (string, error) {
		sz, err := size_for_path(path)
		if err != nil {
			return "", err
		}
		text := fmt.Sprintf("Size: %s", human_readable(sz))
		res := image_collection.ResolutionOf(path)
		if res.Width > -1 {
			text = fmt.Sprintf("Dimensions: %dx%d %s", res.Width, res.Height, text)
		}
		text = place_in(text, available_cols)
		return margin_formatter(strings.Repeat(` `, margin_size)) + formatter(text), err
	})

	if err != nil {
		return nil, err
	}
	ll.image_lines_offset = len(ll.screen_lines)

	do_side := func(path string, filler string) []string {
		if path == "" {
			return nil
		}
		sz, err := image_collection.GetSizeIfAvailable(path, image_size)
		if err == nil {
			count := int(math.Ceil(float64(sz.Height) / float64(screen_size.cell_height)))
			return utils.Repeat(filler, count)
		}
		if errors.Is(err, graphics.ErrNotFound) {
			return style.WrapTextAsLines("Loading image...", "", available_cols)
		}
		return style.WrapTextAsLines(fmt.Sprintf("Failed to load image: %s", err), "", available_cols)
	}
	left_lines := do_side(left_path, removed_format(strings.Repeat(` `, available_cols)))
	if ll.left_image.count = len(left_lines); ll.left_image.count > 0 {
		ll.left_image.key = left_path
	}
	right_lines := do_side(right_path, added_format(strings.Repeat(` `, available_cols)))
	if ll.right_image.count = len(right_lines); ll.right_image.count > 0 {
		ll.right_image.key = right_path
	}
	filler := filler_format(strings.Repeat(` `, available_cols))
	m := strings.Repeat(` `, margin_size)
	get_line := func(i int, which []string, margin_fmt func(...any) string) string {
		if i < len(which) {
			return margin_fmt(m) + which[i]
		}
		return margin_filler_format(m) + filler
	}
	for i := 0; i < utils.Max(len(left_lines), len(right_lines)); i++ {
		left, right := get_line(i, left_lines, removed_margin_format), get_line(i, right_lines, added_margin_format)
		ll.screen_lines = append(ll.screen_lines, join_half_lines(left, right))
	}

	ll.line_type = IMAGE_LINE
	return append(ans, ll), nil
}

type formatter = func(...any) string

func first_binary_line(left_path, right_path string, columns, margin_size int, renderer func(path string, formatter, margin_formatter formatter) (string, error)) (*LogicalLine, error) {
	available_cols := columns/2 - margin_size
	line := ""
	if left_path == "" {
		filler := render_diff_line(``, ``, `filler`, margin_size, available_cols)
		r, err := renderer(right_path, added_format, added_margin_format)
		if err != nil {
			return nil, err
		}
		line = join_half_lines(filler, r)
	} else if right_path == "" {
		filler := render_diff_line(``, ``, `filler`, margin_size, available_cols)
		l, err := renderer(left_path, removed_format, removed_margin_format)
		if err != nil {
			return nil, err
		}
		line = join_half_lines(l, filler)
	} else {
		l, err := renderer(left_path, removed_format, removed_margin_format)
		if err != nil {
			return nil, err
		}
		r, err := renderer(right_path, added_format, added_margin_format)
		if err != nil {
			return nil, err
		}
		line = join_half_lines(l, r)
	}
	ref := left_path
	if ref == "" {
		ref = right_path
	}
	ll := LogicalLine{is_change_start: true, line_type: CHANGE_LINE, src: Reference{path: ref, linenum: 0}, screen_lines: []string{line}}
	if left_path == "" {
		ll.src.path = right_path
	}
	return &ll, nil
}

func binary_lines(left_path, right_path string, columns, margin_size int, ans []*LogicalLine) (ans2 []*LogicalLine, err error) {
	available_cols := columns/2 - margin_size
	ll, err := first_binary_line(left_path, right_path, columns, margin_size, func(path string, formatter, margin_formatter formatter) (string, error) {
		sz, err := size_for_path(path)
		if err != nil {
			return "", err
		}
		text := fmt.Sprintf("Binary file: %s", human_readable(sz))
		text = place_in(text, available_cols)
		return margin_formatter(strings.Repeat(` `, margin_size)) + formatter(text), err
	})

	if err != nil {
		return nil, err
	}
	return append(ans, ll), nil
}

type DiffData struct {
	left_path, right_path       string
	available_cols, margin_size int

	left_lines, right_lines                          []string
	filler_line, left_filler_line, right_filler_line string
}

func hunk_title(hunk_num int, hunk *Hunk, margin_size, available_cols int) string {
	m := hunk_margin_format(strings.Repeat(" ", margin_size))
	t := fmt.Sprintf("@@ -%d,%d +%d,%d @@ %s", hunk.left_start+1, hunk.left_count, hunk.right_start+1, hunk.right_count, hunk.title)
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
				line = join_half_lines(line, line)
			} else {
				line = join_half_lines(line, render_diff_line(right_line_number_s, text, `context`, data.margin_size, data.available_cols))
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
	size := center.left_size
	if ltype != "remove" {
		size = center.right_size
	}
	if size > 0 {
		span := center_span(ltype, center.offset, size)
		line = sgr.InsertFormatting(line, span)
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
			logline.screen_lines = append(logline.screen_lines, join_half_lines(ll[l], rl[l]))
		}
		ans = append(ans, &logline)
	}
	return ans
}

func lines_for_diff(left_path string, right_path string, patch *Patch, columns, margin_size int, ans []*LogicalLine) (result []*LogicalLine, err error) {
	ht := LogicalLine{line_type: HUNK_TITLE_LINE, src: Reference{path: left_path}}
	if patch.Len() == 0 {
		ht.screen_lines = []string{"The files are identical"}
		ht.line_type = EMPTY_LINE
		ans = append(ans, &ht)
		return ans, nil
	}
	available_cols := columns/2 - margin_size
	data := DiffData{left_path: left_path, right_path: right_path, available_cols: available_cols, margin_size: margin_size}
	if left_path != "" {
		data.left_lines, err = highlighted_lines_for_path(left_path)
		if err != nil {
			return
		}
	}
	if right_path != "" {
		data.right_lines, err = highlighted_lines_for_path(right_path)
		if err != nil {
			return
		}
	}
	data.filler_line = render_diff_line("", "", "filler", margin_size, available_cols)
	data.left_filler_line = render_diff_line("", "", "remove", margin_size, available_cols)
	data.right_filler_line = render_diff_line("", "", "add", margin_size, available_cols)

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
	lines, err := highlighted_lines_for_path(path)
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
				text = join_half_lines(empty, hl)
			} else {
				text = join_half_lines(hl, empty)
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

func render(collection *Collection, diff_map map[string]*Patch, screen_size screen_size, largest_line_number int, image_size graphics.Size) (result *LogicalLines, err error) {
	margin_size := utils.Max(3, len(strconv.Itoa(largest_line_number))+1)
	ans := make([]*LogicalLine, 0, 1024)
	empty_line := LogicalLine{line_type: EMPTY_LINE}
	columns := screen_size.columns
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
					ans, err = image_lines(path, changed_path, screen_size, margin_size, image_size, ans)
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
					ans, err = image_lines("", path, screen_size, margin_size, image_size, ans)
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
					ans, err = image_lines(path, "", screen_size, margin_size, image_size, ans)
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
