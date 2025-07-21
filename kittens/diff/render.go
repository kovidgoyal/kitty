// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"errors"
	"fmt"
	"math"
	"os"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/sgr"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type LineType int

const (
	TITLE_LINE LineType = iota
	CHANGE_LINE
	CONTEXT_LINE
	HUNK_TITLE_LINE
	IMAGE_LINE
	EMPTY_LINE
)

type Reference struct {
	path    string
	linenum int // 1 based
}

type HalfScreenLine struct {
	marked_up_margin_text string
	marked_up_text        string
	is_filler             bool
	cached_wcswidth       int
}

func (self *HalfScreenLine) wcswidth() int {
	if self.cached_wcswidth == 0 && self.marked_up_text != "" {
		self.cached_wcswidth = wcswidth.Stringwidth(self.marked_up_text)
	}
	return self.cached_wcswidth
}

type ScreenLine struct {
	left, right HalfScreenLine
}

type LogicalLine struct {
	line_type                       LineType
	screen_lines                    []*ScreenLine
	is_full_width                   bool
	is_change_start                 bool
	left_reference, right_reference Reference
	left_image, right_image         struct {
		key   string
		count int
	}
	image_lines_offset int
}

func (self *LogicalLine) render_screen_line(n int, lp *loop.Loop, margin_size, columns int) {
	if n >= len(self.screen_lines) || n < 0 {
		return
	}
	sl := self.screen_lines[n]
	available_cols := columns/2 - margin_size
	if self.is_full_width {
		available_cols = columns - margin_size
	}
	left_margin := place_in(sl.left.marked_up_margin_text, margin_size)
	left_text := place_in(sl.left.marked_up_text, available_cols)
	if sl.left.is_filler {
		left_margin = format_as_sgr.margin_filler + left_margin
		left_text = format_as_sgr.filler + left_text
	} else {
		switch self.line_type {
		case CHANGE_LINE, IMAGE_LINE:
			left_margin = format_as_sgr.removed_margin + left_margin
			left_text = format_as_sgr.removed + left_text
		case HUNK_TITLE_LINE:
			left_margin = format_as_sgr.hunk_margin + left_margin
			left_text = format_as_sgr.hunk + left_text
		case TITLE_LINE:
		default:
			left_margin = format_as_sgr.margin + left_margin
		}
	}
	lp.QueueWriteString(left_margin + "\x1b[m")
	lp.QueueWriteString(left_text)
	if self.is_full_width {
		return
	}
	right_margin := place_in(sl.right.marked_up_margin_text, margin_size)
	right_text := place_in(sl.right.marked_up_text, available_cols)
	if sl.right.is_filler {
		right_margin = format_as_sgr.margin_filler + right_margin
		right_text = format_as_sgr.filler + right_text
	} else {
		switch self.line_type {
		case CHANGE_LINE, IMAGE_LINE:
			right_margin = format_as_sgr.added_margin + right_margin
			right_text = format_as_sgr.added + right_text
		case HUNK_TITLE_LINE:
			right_margin = format_as_sgr.hunk_margin + right_margin
			right_text = format_as_sgr.hunk + right_text
		case TITLE_LINE:
		default:
			right_margin = format_as_sgr.margin + right_margin
		}
	}
	lp.QueueWriteString("\x1b[m\r")
	lp.MoveCursorHorizontally(available_cols + margin_size)
	lp.QueueWriteString(right_margin + "\x1b[m")
	lp.QueueWriteString(right_text)
}

func (self *LogicalLine) IncrementScrollPosBy(pos *ScrollPos, amt int) (delta int) {
	if len(self.screen_lines) > 0 {
		npos := utils.Max(0, utils.Min(pos.screen_line+amt, len(self.screen_lines)-1))
		delta = npos - pos.screen_line
		pos.screen_line = npos
	}
	return
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

var format_as_sgr struct {
	title, margin, added, removed, added_margin, removed_margin, filler, margin_filler, hunk_margin, hunk, selection, search string
}

var statusline_format, added_count_format, removed_count_format, message_format func(...any) string
var use_light_colors bool = false

type ResolvedColors struct {
	Added_bg             style.RGBA
	Added_margin_bg      style.RGBA
	Background           style.RGBA
	Filler_bg            style.RGBA
	Foreground           style.RGBA
	Highlight_added_bg   style.RGBA
	Highlight_removed_bg style.RGBA
	Hunk_bg              style.RGBA
	Hunk_margin_bg       style.RGBA
	Margin_bg            style.RGBA
	Margin_fg            style.RGBA
	Margin_filler_bg     style.NullableColor
	Removed_bg           style.RGBA
	Removed_margin_bg    style.RGBA
	Search_bg            style.RGBA
	Search_fg            style.RGBA
	Select_bg            style.RGBA
	Select_fg            style.NullableColor
	Title_bg             style.RGBA
	Title_fg             style.RGBA
}

var resolved_colors ResolvedColors

func create_formatters() {
	rc := &resolved_colors
	if !use_light_colors {
		rc.Added_bg = conf.Dark_added_bg
		rc.Added_margin_bg = conf.Dark_added_margin_bg
		rc.Background = conf.Dark_background
		rc.Filler_bg = conf.Dark_filler_bg
		rc.Foreground = conf.Dark_foreground
		rc.Highlight_added_bg = conf.Dark_highlight_added_bg
		rc.Highlight_removed_bg = conf.Dark_highlight_removed_bg
		rc.Hunk_bg = conf.Dark_hunk_bg
		rc.Hunk_margin_bg = conf.Dark_hunk_margin_bg
		rc.Margin_bg = conf.Dark_margin_bg
		rc.Margin_fg = conf.Dark_margin_fg
		rc.Margin_filler_bg = conf.Dark_margin_filler_bg
		rc.Removed_bg = conf.Dark_removed_bg
		rc.Removed_margin_bg = conf.Dark_removed_margin_bg
		rc.Search_bg = conf.Dark_search_bg
		rc.Search_fg = conf.Dark_search_fg
		rc.Select_bg = conf.Dark_select_bg
		rc.Select_fg = conf.Dark_select_fg
		rc.Title_bg = conf.Dark_title_bg
		rc.Title_fg = conf.Dark_title_fg
	} else {
		rc.Added_bg = conf.Added_bg
		rc.Added_margin_bg = conf.Added_margin_bg
		rc.Background = conf.Background
		rc.Filler_bg = conf.Filler_bg
		rc.Foreground = conf.Foreground
		rc.Highlight_added_bg = conf.Highlight_added_bg
		rc.Highlight_removed_bg = conf.Highlight_removed_bg
		rc.Hunk_bg = conf.Hunk_bg
		rc.Hunk_margin_bg = conf.Hunk_margin_bg
		rc.Margin_bg = conf.Margin_bg
		rc.Margin_fg = conf.Margin_fg
		rc.Margin_filler_bg = conf.Margin_filler_bg
		rc.Removed_bg = conf.Removed_bg
		rc.Removed_margin_bg = conf.Removed_margin_bg
		rc.Search_bg = conf.Search_bg
		rc.Search_fg = conf.Search_fg
		rc.Select_bg = conf.Select_bg
		rc.Select_fg = conf.Select_fg
		rc.Title_bg = conf.Title_bg
		rc.Title_fg = conf.Title_fg
	}
	ctx := style.Context{AllowEscapeCodes: true}
	only_open := func(x string) string {
		ans := ctx.SprintFunc(x)("|")
		ans, _, _ = strings.Cut(ans, "|")
		return ans
	}
	format_as_sgr.filler = only_open("bg=" + rc.Filler_bg.AsRGBSharp())
	if rc.Margin_filler_bg.IsSet {
		format_as_sgr.margin_filler = only_open("bg=" + rc.Margin_filler_bg.Color.AsRGBSharp())
	} else {
		format_as_sgr.margin_filler = only_open("bg=" + rc.Filler_bg.AsRGBSharp())
	}
	format_as_sgr.added = only_open("bg=" + rc.Added_bg.AsRGBSharp())
	format_as_sgr.added_margin = only_open(fmt.Sprintf("fg=%s bg=%s", rc.Margin_fg.AsRGBSharp(), rc.Added_margin_bg.AsRGBSharp()))
	format_as_sgr.removed = only_open("bg=" + rc.Removed_bg.AsRGBSharp())
	format_as_sgr.removed_margin = only_open(fmt.Sprintf("fg=%s bg=%s", rc.Margin_fg.AsRGBSharp(), rc.Removed_margin_bg.AsRGBSharp()))
	format_as_sgr.title = only_open(fmt.Sprintf("fg=%s bg=%s bold", rc.Title_fg.AsRGBSharp(), rc.Title_bg.AsRGBSharp()))
	format_as_sgr.margin = only_open(fmt.Sprintf("fg=%s bg=%s", rc.Margin_fg.AsRGBSharp(), rc.Margin_bg.AsRGBSharp()))
	format_as_sgr.hunk = only_open(fmt.Sprintf("fg=%s bg=%s", rc.Margin_fg.AsRGBSharp(), rc.Hunk_bg.AsRGBSharp()))
	format_as_sgr.hunk_margin = only_open(fmt.Sprintf("fg=%s bg=%s", rc.Margin_fg.AsRGBSharp(), rc.Hunk_margin_bg.AsRGBSharp()))
	format_as_sgr.search = only_open(fmt.Sprintf("fg=%s bg=%s", rc.Search_fg.AsRGBSharp(), rc.Search_bg.AsRGBSharp()))
	statusline_format = ctx.SprintFunc(fmt.Sprintf("fg=%s", rc.Margin_fg.AsRGBSharp()))
	added_count_format = ctx.SprintFunc(fmt.Sprintf("fg=%s", rc.Highlight_added_bg.AsRGBSharp()))
	removed_count_format = ctx.SprintFunc(fmt.Sprintf("fg=%s", rc.Highlight_removed_bg.AsRGBSharp()))
	message_format = ctx.SprintFunc("bold")
	if rc.Select_fg.IsSet {
		format_as_sgr.selection = only_open(fmt.Sprintf("fg=%s bg=%s", rc.Select_fg.Color.AsRGBSharp(), rc.Select_bg.AsRGBSharp()))
	} else {
		format_as_sgr.selection = only_open("bg=" + rc.Select_bg.AsRGBSharp())
	}
}

func center_span(ltype string, offset, size int) *sgr.Span {
	ans := sgr.NewSpan(offset, size)
	switch ltype {
	case "add":
		ans.SetBackground(resolved_colors.Highlight_added_bg).SetClosingBackground(resolved_colors.Added_bg)
	case "remove":
		ans.SetBackground(resolved_colors.Highlight_removed_bg).SetClosingBackground(resolved_colors.Removed_bg)
	}
	return ans
}

func title_lines(left_path, right_path string, columns, margin_size int, ans []*LogicalLine) []*LogicalLine {
	left_name, right_name := path_name_map[left_path], path_name_map[right_path]
	available_cols := columns/2 - margin_size
	ll := LogicalLine{
		line_type:      TITLE_LINE,
		left_reference: Reference{path: left_path}, right_reference: Reference{path: right_path},
	}
	sl := ScreenLine{}
	if right_name != "" && right_name != left_name {
		sl.left.marked_up_text = format_as_sgr.title + fit_in(sanitize(left_name), available_cols)
		sl.right.marked_up_text = format_as_sgr.title + fit_in(sanitize(right_name), available_cols)
	} else {
		sl.left.marked_up_text = format_as_sgr.title + fit_in(sanitize(left_name), columns-margin_size)
		ll.is_full_width = true
	}
	l2 := ll
	l2.line_type = EMPTY_LINE
	ll.screen_lines = append(ll.screen_lines, &sl)
	sl2 := ScreenLine{}
	sl2.left.marked_up_margin_text = "\x1b[m" + strings.Repeat("━", margin_size)
	sl2.left.marked_up_text = strings.Repeat("━", columns-margin_size)
	l2.is_full_width = true
	l2.screen_lines = append(l2.screen_lines, &sl2)
	return append(ans, &ll, &l2)
}

type LogicalLines struct {
	lines                []*LogicalLine
	margin_size, columns int
}

func (self *LogicalLines) At(i int) *LogicalLine { return self.lines[i] }

func (self *LogicalLines) ScreenLineAt(pos ScrollPos) *ScreenLine {
	if pos.logical_line < len(self.lines) && pos.logical_line >= 0 {
		line := self.lines[pos.logical_line]
		if pos.screen_line < len(line.screen_lines) && pos.screen_line >= 0 {
			return self.lines[pos.logical_line].screen_lines[pos.screen_line]
		}
	}
	return nil
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

func image_lines(left_path, right_path string, screen_size screen_size, margin_size int, image_size graphics.Size, ans []*LogicalLine) ([]*LogicalLine, error) {
	columns := screen_size.columns
	available_cols := columns/2 - margin_size
	ll, err := first_binary_line(left_path, right_path, columns, margin_size, func(path string) (string, error) {
		sz, err := size_for_path(path)
		if err != nil {
			return "", err
		}
		text := fmt.Sprintf("Size: %s", human_readable(sz))
		res := image_collection.ResolutionOf(path)
		if res.Width > -1 {
			text = fmt.Sprintf("Dimensions: %dx%d %s", res.Width, res.Height, text)
		}
		return text, nil
	})

	if err != nil {
		return nil, err
	}
	ll.image_lines_offset = len(ll.screen_lines)

	do_side := func(path string) []string {
		if path == "" {
			return nil
		}
		sz, err := image_collection.GetSizeIfAvailable(path, image_size)
		if err == nil {
			count := int(math.Ceil(float64(sz.Height) / float64(screen_size.cell_height)))
			return utils.Repeat("", count)
		}
		if errors.Is(err, graphics.ErrNotFound) {
			return splitlines("Loading image...", available_cols)
		}
		return splitlines(fmt.Sprintf("%s", err), available_cols)
	}
	left_lines := do_side(left_path)
	if ll.left_image.count = len(left_lines); ll.left_image.count > 0 {
		ll.left_image.key = left_path
	}
	right_lines := do_side(right_path)
	if ll.right_image.count = len(right_lines); ll.right_image.count > 0 {
		ll.right_image.key = right_path
	}
	for i := 0; i < utils.Max(len(left_lines), len(right_lines)); i++ {
		sl := ScreenLine{}
		if i < len(left_lines) {
			sl.left.marked_up_text = left_lines[i]
		} else {
			sl.left.is_filler = true
		}
		if i < len(right_lines) {
			sl.right.marked_up_text = right_lines[i]
		} else {
			sl.right.is_filler = true
		}
		ll.screen_lines = append(ll.screen_lines, &sl)
	}
	ll.line_type = IMAGE_LINE
	return append(ans, ll), nil
}

func first_binary_line(left_path, right_path string, columns, margin_size int, renderer func(path string) (string, error)) (*LogicalLine, error) {
	available_cols := columns/2 - margin_size
	ll := LogicalLine{
		is_change_start: true, line_type: CHANGE_LINE,
		left_reference: Reference{path: left_path}, right_reference: Reference{path: right_path},
	}
	if left_path == "" {
		line, err := renderer(right_path)
		if err != nil {
			return nil, err
		}
		for _, x := range splitlines(line, available_cols) {
			sl := ScreenLine{}
			sl.right.marked_up_text = x
			sl.left.is_filler = true
			ll.screen_lines = append(ll.screen_lines, &sl)
		}
	} else if right_path == "" {
		line, err := renderer(left_path)
		if err != nil {
			return nil, err
		}
		for _, x := range splitlines(line, available_cols) {
			sl := ScreenLine{}
			sl.right.is_filler = true
			sl.left.marked_up_text = x
			ll.screen_lines = append(ll.screen_lines, &sl)
		}
	} else {
		l, err := renderer(left_path)
		if err != nil {
			return nil, err
		}
		r, err := renderer(right_path)
		if err != nil {
			return nil, err
		}
		left_lines, right_lines := splitlines(l, available_cols), splitlines(r, available_cols)
		for i := 0; i < utils.Max(len(left_lines), len(right_lines)); i++ {
			sl := ScreenLine{}
			if i < len(left_lines) {
				sl.left.marked_up_text = left_lines[i]
			}
			if i < len(right_lines) {
				sl.right.marked_up_text = right_lines[i]
			}
			ll.screen_lines = append(ll.screen_lines, &sl)
		}
	}
	return &ll, nil
}

func binary_lines(left_path, right_path string, columns, margin_size int, ans []*LogicalLine) (ans2 []*LogicalLine, err error) {
	ll, err := first_binary_line(left_path, right_path, columns, margin_size, func(path string) (string, error) {
		sz, err := size_for_path(path)
		if err != nil {
			return "", err
		}
		return fmt.Sprintf("Binary file: %s", human_readable(sz)), nil
	})

	if err != nil {
		return nil, err
	}
	return append(ans, ll), nil
}

type DiffData struct {
	left_path, right_path       string
	available_cols, margin_size int

	left_lines, right_lines []string
}

func hunk_title(hunk *Hunk) string {
	return fmt.Sprintf("@@ -%d,%d +%d,%d @@ %s", hunk.left_start+1, hunk.left_count, hunk.right_start+1, hunk.right_count, hunk.title)
}

func lines_for_context_chunk(data *DiffData, _ int, chunk *Chunk, _ int, ans []*LogicalLine) []*LogicalLine {
	for i := 0; i < chunk.left_count; i++ {
		left_line_number := chunk.left_start + i
		right_line_number := chunk.right_start + i
		ll := LogicalLine{line_type: CONTEXT_LINE,
			left_reference:  Reference{path: data.left_path, linenum: left_line_number + 1},
			right_reference: Reference{path: data.right_path, linenum: right_line_number + 1},
		}
		left_line_number_s := strconv.Itoa(left_line_number + 1)
		right_line_number_s := strconv.Itoa(right_line_number + 1)
		for _, text := range splitlines(data.left_lines[left_line_number], data.available_cols) {
			left_line := HalfScreenLine{marked_up_margin_text: left_line_number_s, marked_up_text: text}
			right_line := left_line
			if right_line_number_s != left_line_number_s {
				right_line = HalfScreenLine{marked_up_margin_text: right_line_number_s, marked_up_text: text}
			}
			ll.screen_lines = append(ll.screen_lines, &ScreenLine{left_line, right_line})
			left_line_number_s, right_line_number_s = "", ""
		}
		ans = append(ans, &ll)
	}
	return ans
}

func splitlines(text string, width int) []string {
	return style.WrapTextAsLines(text, width, style.WrapOptions{})
}

func render_half_line(line_number int, line, ltype string, available_cols int, center Center, ans []HalfScreenLine) []HalfScreenLine {
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
		ans = append(ans, HalfScreenLine{marked_up_margin_text: lnum, marked_up_text: sc})
		lnum = ""
	}
	return ans
}

func lines_for_diff_chunk(data *DiffData, _ int, chunk *Chunk, _ int, ans []*LogicalLine) []*LogicalLine {
	common := utils.Min(chunk.left_count, chunk.right_count)
	ll, rl := make([]HalfScreenLine, 0, 32), make([]HalfScreenLine, 0, 32)
	for i := 0; i < utils.Max(chunk.left_count, chunk.right_count); i++ {
		ll, rl = ll[:0], rl[:0]
		var center Center
		left_lnum, right_lnum := 0, 0
		if i < len(chunk.centers) {
			center = chunk.centers[i]
		}
		if i < chunk.left_count {
			left_lnum = chunk.left_start + i
			ll = render_half_line(left_lnum, data.left_lines[left_lnum], "remove", data.available_cols, center, ll)
			left_lnum++
		}

		if i < chunk.right_count {
			right_lnum = chunk.right_start + i
			rl = render_half_line(right_lnum, data.right_lines[right_lnum], "add", data.available_cols, center, rl)
			right_lnum++
		}

		if i < common {
			extra := len(ll) - len(rl)
			if extra < 0 {
				ll = append(ll, utils.Repeat(HalfScreenLine{}, -extra)...)
			} else if extra > 0 {
				rl = append(rl, utils.Repeat(HalfScreenLine{}, extra)...)
			}
		} else {
			if len(ll) > 0 {
				rl = append(rl, utils.Repeat(HalfScreenLine{is_filler: true}, len(ll))...)
			} else if len(rl) > 0 {
				ll = append(ll, utils.Repeat(HalfScreenLine{is_filler: true}, len(rl))...)
			}
		}
		logline := LogicalLine{
			line_type: CHANGE_LINE, is_change_start: i == 0,
			left_reference:  Reference{path: data.left_path, linenum: left_lnum},
			right_reference: Reference{path: data.left_path, linenum: right_lnum},
		}
		for l := 0; l < len(ll); l++ {
			logline.screen_lines = append(logline.screen_lines, &ScreenLine{left: ll[l], right: rl[l]})
		}
		ans = append(ans, &logline)
	}
	return ans
}

func lines_for_diff(left_path string, right_path string, patch *Patch, columns, margin_size int, ans []*LogicalLine) (result []*LogicalLine, err error) {
	ht := LogicalLine{
		line_type:      HUNK_TITLE_LINE,
		left_reference: Reference{path: left_path}, right_reference: Reference{path: right_path},
		is_full_width: true,
	}
	if patch.Len() == 0 {
		txt := "The files are identical"
		if lstat, err := os.Stat(left_path); err == nil {
			if rstat, err := os.Stat(right_path); err == nil {
				if lstat.Mode() != rstat.Mode() {
					txt = fmt.Sprintf("Mode changed: %s to %s", lstat.Mode(), rstat.Mode())
				}
			}
		}
		for _, line := range splitlines(txt, columns-margin_size) {
			sl := ScreenLine{}
			sl.left.marked_up_text = line
			ht.screen_lines = append(ht.screen_lines, &sl)
		}
		ht.line_type = EMPTY_LINE
		ht.is_full_width = true
		return append(ans, &ht), nil
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

	for hunk_num, hunk := range patch.all_hunks {
		htl := ht
		htl.left_reference.linenum = hunk.left_start + 1
		htl.right_reference.linenum = hunk.right_start + 1
		for _, line := range splitlines(hunk_title(hunk), columns-margin_size) {
			sl := ScreenLine{}
			sl.left.marked_up_text = line
			htl.screen_lines = append(htl.screen_lines, &sl)
		}
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
	ll := LogicalLine{line_type: CHANGE_LINE}
	if !is_add {
		ltype = `remove`
		ll.left_reference.path = path
	} else {
		ll.right_reference.path = path
	}
	lines, err := highlighted_lines_for_path(path)
	if err != nil {
		return nil, err
	}
	var msg_lines []string
	if is_add {
		msg_lines = splitlines(`This file was added`, available_cols)
	} else {
		msg_lines = splitlines(`This file was removed`, available_cols)
	}
	for line_number, line := range lines {
		hlines := make([]HalfScreenLine, 0, 8)
		hlines = render_half_line(line_number, line, ltype, available_cols, Center{}, hlines)
		l := ll
		if is_add {
			l.right_reference.linenum = line_number + 1
		} else {
			l.left_reference.linenum = line_number + 1
		}
		l.is_change_start = line_number == 0
		for i, hl := range hlines {
			sl := ScreenLine{}
			if is_add {
				sl.right = hl
				if len(msg_lines) > 0 {
					sl.left.marked_up_text = msg_lines[i]
					sl.left.is_filler = true
					msg_lines = msg_lines[1:]
				} else {
					sl.left.is_filler = true
				}
			} else {
				sl.left = hl
				if len(msg_lines) > 0 {
					sl.right.marked_up_text = msg_lines[i]
					sl.right.is_filler = true
					msg_lines = msg_lines[1:]
				} else {
					sl.right.is_filler = true
				}
			}
			l.screen_lines = append(l.screen_lines, &sl)
		}
		ans = append(ans, &l)
	}
	return ans, nil
}

func rename_lines(path, other_path string, columns, margin_size int, ans []*LogicalLine) ([]*LogicalLine, error) {
	ll := LogicalLine{
		left_reference: Reference{path: path}, right_reference: Reference{path: other_path},
		line_type: CHANGE_LINE, is_change_start: true, is_full_width: true}
	for _, line := range splitlines(fmt.Sprintf(`The file %s was renamed to %s`, sanitize(path_name_map[path]), sanitize(path_name_map[other_path])), columns-margin_size) {
		sl := ScreenLine{}
		sl.right.marked_up_text = line
		ll.screen_lines = append(ll.screen_lines, &sl)
	}
	return append(ans, &ll), nil
}

func render(collection *Collection, diff_map map[string]*Patch, screen_size screen_size, largest_line_number int, image_size graphics.Size) (result *LogicalLines, err error) {
	margin_size := utils.Max(3, len(strconv.Itoa(largest_line_number))+1)
	ans := make([]*LogicalLine, 0, 1024)
	columns := screen_size.columns
	err = collection.Apply(func(path, item_type, changed_path string) error {
		ans = title_lines(path, changed_path, columns, margin_size, ans)
		defer func() {
			ans = append(ans, &LogicalLine{line_type: EMPTY_LINE, screen_lines: []*ScreenLine{{}}})
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
	var ll []*LogicalLine
	if len(ans) > 1 {
		ll = ans[:len(ans)-1]
	} else {
		// Having am empty list of lines causes panics later on
		ll = []*LogicalLine{{line_type: EMPTY_LINE, screen_lines: []*ScreenLine{{}}}}
	}
	return &LogicalLines{lines: ll, margin_size: margin_size, columns: columns}, err
}
