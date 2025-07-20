package choose_files

import (
	"fmt"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/icons"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

func (h *Handler) draw_results_title() {
	text := filepath.Clean(h.state.CurrentDir())
	home := filepath.Clean(utils.Expanduser("~"))
	if strings.HasPrefix(text, home) {
		text = "~" + text[len(home):]
	}
	text = sanitize(text)
	available_width := h.screen_size.width - 9
	if available_width < 2 {
		return
	}
	tt := wcswidth.TruncateToVisualLength(text, available_width)
	if len(tt) < len(text) {
		text = wcswidth.TruncateToVisualLength(text, available_width-1)
	}
	text = fmt.Sprintf(" %s %s ", h.lp.SprintStyled("fg=blue", icons.IconForFileWithMode(text, fs.ModeDir, false)+" "), h.lp.SprintStyled("fg=intense-white bold", text))
	extra := available_width - wcswidth.Stringwidth(text)
	x := 3
	if extra > 1 {
		x += extra / 2
	}
	h.lp.MoveCursorHorizontally(x)
	h.lp.QueueWriteString(text)
}

func (h *Handler) draw_no_matches_message(in_progress bool) {
	text := "Scanning filesystem, please wait…"
	if !in_progress {
		text = utils.IfElse(h.state.SearchText() == "", "No files present in this folder", "No matches found")
	}
	for _, line := range style.WrapTextAsLines(text, h.screen_size.width-2, style.WrapOptions{}) {
		h.lp.QueueWriteString("\r")
		h.lp.MoveCursorHorizontally(1)
		h.lp.QueueWriteString(line)
		h.lp.MoveCursorVertically(1)
	}

}

const matching_position_style = "fg=green"
const selected_style = "fg=magenta"
const current_style = "fg=intense-white bold"

func (h *Handler) render_match_with_positions(text string, add_ellipsis bool, positions []int, is_current bool) {
	prefix, suffix, _ := strings.Cut(h.lp.SprintStyled(matching_position_style, " "), " ")
	if is_current {
		p, s, _ := strings.Cut(h.lp.SprintStyled(current_style, " "), " ")
		h.lp.QueueWriteString(p)
		defer h.lp.QueueWriteString(s)
		suffix += p
	}
	write_chunk := func(text string, emphasize bool) {
		if text == "" {
			return
		}
		if emphasize {
			h.lp.QueueWriteString(prefix)
			defer func() {
				h.lp.QueueWriteString(suffix)
			}()
		}
		h.lp.QueueWriteString(text)
	}
	at := 0
	limit := len(text)
	for _, p := range positions {
		if p > limit || at > limit {
			break
		}
		write_chunk(text[at:p], false)
		at = p
		if r, sz := utf8.DecodeRuneInString(text[p:]); r != utf8.RuneError {
			write_chunk(string(r), true)
			at += sz
		}
	}
	if at < len(text) {
		write_chunk(text[at:], false)
	}
	if add_ellipsis {
		write_chunk("…", false)
	}
}

var icon_cache map[string]string

func icon_for(path string, x os.FileMode) string {
	if icon_cache == nil {
		icon_cache = make(map[string]string, 512)
	}
	if ans := icon_cache[path]; ans != "" {
		return ans
	}
	var ans string
	if x&fs.ModeSymlink != 0 && x&SymlinkToDir != 0 {
		ans = string(icons.SYMLINK_TO_DIR)
	} else {
		ans = icons.IconForFileWithMode(path, x, true)
	}
	if wcswidth.Stringwidth(ans) == 1 {
		ans += " "
	}
	icon_cache[path] = ans
	return ans
}

func (h *Handler) draw_column_of_matches(matches ResultsType, current_idx int, x, y, available_width, colnum int) {
	root_dir := h.state.CurrentDir()
	for i, m := range matches {
		h.lp.QueueWriteString("\r")
		h.lp.MoveCursorHorizontally(x)
		is_selected := h.state.IsSelected(m)
		var icon string
		if is_selected {
			icon = "󰗠 "
		} else {
			icon = icon_for(filepath.Join(root_dir, m.text), m.ftype)
		}
		text := sanitize(m.text)
		add_ellipsis := false
		width := wcswidth.Stringwidth(text)
		if width > available_width-3 {
			text = wcswidth.TruncateToVisualLength(text, available_width-4)
			add_ellipsis = true
			width = available_width - 3
		}
		is_current := i == current_idx
		if is_current {
			h.lp.QueueWriteString(h.lp.SprintStyled(matching_position_style, icon+" "))
		} else {
			if is_selected {
				h.lp.QueueWriteString(h.lp.SprintStyled(selected_style, icon+" "))
			} else {
				h.lp.QueueWriteString(icon + " ")
			}
		}
		h.render_match_with_positions(text, add_ellipsis, m.sorted_positions(), is_current)
		h.lp.MoveCursorVertically(1)
		cr := h.state.mouse_state.AddCellRegion(fmt.Sprintf("result-%d-%d", colnum, i), x, y-1+i, x+width+2, y-1+i)
		cr.HoverStyle = HOVER_STYLE
		var data struct {
			colnum, i int
		}
		data.colnum, data.i = colnum, i
		cr.OnClickEvent = func(id string, ev *loop.MouseEvent, cell_offset tui.Point) error {
			if ev.Buttons&loop.LEFT_MOUSE_BUTTON == 0 {
				return nil
			}
			ctrl_mod := utils.IfElse(runtime.GOOS == "darwin", loop.SUPER, loop.CTRL)
			mods := ev.Mods & (ctrl_mod | loop.ALT) // shift alone and ctrl+shift are used for kitty bindings
			matches, _ := h.get_results()
			num_before := h.state.last_render.num_of_slots*data.colnum + data.i
			idx, did_wrap := matches.IncrementIndexWithWrapAroundAndCheck(h.state.last_render.first_idx, num_before)
			if did_wrap {
				h.lp.Beep()
				return nil
			}
			d := matches.SignedDistance(idx, h.state.current_idx)
			h.state.SetCurrentIndex(idx)
			h.state.last_render.num_before = max(0, h.state.last_render.num_before+d)
			switch mods {
			case 0:
				h.dispatch_action("accept", "")
			case ctrl_mod, ctrl_mod | loop.ALT:
				h.dispatch_action("select", "")
			case loop.ALT:
				r := matches.At(idx)
				if (r != nil && h.state.IsSelected(r)) || h.result_manager.last_click_anchor == nil {
					h.dispatch_action("select", "")
					return nil
				}
				already_selected := utils.NewSetWithItems(h.state.selections...)
				cdir := h.state.CurrentDir()
				matches.Apply(idx, *h.result_manager.last_click_anchor, func(r *ResultItem) bool {
					m := filepath.Join(cdir, r.text)
					if !already_selected.Has(m) && h.state.CanSelect(r) {
						already_selected.Add(m)
						h.state.selections = append(h.state.selections, m)
					}
					return true
				})
				return h.draw_screen()

			}
			return nil
		}
	}
}

func (h *Handler) draw_list_of_results(matches *SortedResults, y, height int) (num_cols, num_shown, preview_width int) {
	const BASE_COL_WIDTH = 40
	available_width := h.screen_size.width - 2
	show_preview := h.state.ShowPreview()
	if show_preview && available_width < BASE_COL_WIDTH+30 {
		show_preview = false
	}
	if show_preview {
		switch {
		case available_width < BASE_COL_WIDTH*2:
			preview_width = max(30, available_width/2)
		default:
			preview_width = BASE_COL_WIDTH
		}
		available_width -= preview_width
	}
	col_width := available_width
	num_cols = 1
	calc_num_cols := func(num_matches int) int {
		if num_matches == 0 || height < 2 {
			return 0
		}
		if num_matches > height {
			col_width = BASE_COL_WIDTH
			num_cols = available_width / col_width
			for num_cols > 0 && height*(num_cols-1) >= num_matches {
				num_cols--
			}
			col_width = available_width / num_cols
		}
		return num_cols
	}
	columns, num_before, first_idx := matches.SplitIntoColumns(calc_num_cols, height, h.state.last_render.num_before, h.state.CurrentIndex())
	h.state.last_render.num_before = num_before
	h.state.last_render.num_per_column = height
	h.state.last_render.num_columns = num_cols
	h.state.last_render.first_idx = first_idx
	x := 1
	for i, col := range columns {
		h.lp.MoveCursorTo(x, y)
		h.draw_column_of_matches(col, num_before, x, y, col_width-1, i)
		num_before -= height
		num_shown += len(col)
		x += col_width
	}
	return len(columns), num_shown, preview_width
}

func (h *Handler) draw_num_of_matches(num_shown, y int, in_progress bool) {
	m := ""
	switch h.state.last_render.num_matches {
	case 0:
		m = " no matches "
	default:
		m = fmt.Sprintf(" %d of %s matches ", min(num_shown, h.state.last_render.num_matches), h.msg_printer.Sprint(h.state.last_render.num_matches))
	}
	w := int(math.Ceil(float64(wcswidth.Stringwidth(m)) / 2.0))
	spinner := ""
	spinner_width := 0
	if in_progress {
		spinner = h.spinner.Tick()
		spinner_width = 1 + wcswidth.Stringwidth(spinner)
	}
	h.lp.MoveCursorTo(h.screen_size.width-w-spinner_width-2, y)
	st := loop.SizedText{Subscale_denominator: 2, Subscale_numerator: 1, Vertical_alignment: 2, Width: 1}
	graphemes := wcswidth.SplitIntoGraphemes(m)
	for len(graphemes) > 0 {
		s := ""
		for w := 0; w < 2 && len(graphemes) > 0; {
			w += wcswidth.Stringwidth(graphemes[0])
			s += graphemes[0]
			graphemes = graphemes[1:]
		}
		h.lp.DrawSizedText(s, st)
	}
	if spinner != "" {
		h.lp.QueueWriteString(spinner)
	}
}

func (h *Handler) draw_preview(y int) {
	x := h.screen_size.width - h.state.last_render.preview_width
	height := h.state.last_render.num_of_slots
	buf := strings.Builder{}
	buf.Grow(16 * height)
	buf.WriteString(fmt.Sprintf(loop.MoveCursorToTemplate, y-1, x))
	buf.WriteString("┬")
	for i := range height {
		buf.WriteString(fmt.Sprintf(loop.MoveCursorToTemplate, y+i, x))
		buf.WriteString("│")
	}
	buf.WriteString(fmt.Sprintf(loop.MoveCursorToTemplate, y+height, x))
	buf.WriteString("┴")
	h.lp.QueueWriteString(buf.String())
	h.draw_preview_content(x+1, y, h.state.last_render.preview_width-1, h.state.last_render.num_of_slots)
}

func (h *Handler) draw_results(y, bottom_margin int, matches *SortedResults, in_progress bool) (height int) {
	height = h.screen_size.height - y - bottom_margin
	h.lp.MoveCursorTo(1, 1+y)
	h.draw_frame(h.screen_size.width, height, in_progress)
	h.lp.MoveCursorTo(1, 1+y)
	h.draw_results_title()
	y += 2
	h.lp.MoveCursorTo(1, y)
	h.state.last_render.num_of_slots = height - 2
	num_cols := 0
	num := matches.Len()
	num_shown := 0
	h.state.last_render.preview_width = 0
	switch num {
	case 0:
		h.draw_no_matches_message(in_progress)
	default:
		num_cols, num_shown, h.state.last_render.preview_width = h.draw_list_of_results(matches, y, h.state.last_render.num_of_slots)
	}
	h.state.last_render.num_matches = num
	h.state.last_render.num_shown = num_shown
	h.draw_num_of_matches(h.state.last_render.num_of_slots*num_cols, y+height-2, in_progress)
	if h.state.last_render.preview_width > 0 {
		h.draw_preview(y)
	}
	return
}

func (h *Handler) next_result(amt int) {
	if h.state.last_render.num_matches > 0 {
		idx := h.state.CurrentIndex()
		idx = h.result_manager.scorer.sorted_results.IncrementIndexWithWrapAround(idx, amt)
		h.state.SetCurrentIndex(idx)
		h.state.last_render.num_before = max(0, h.state.last_render.num_before+amt)
	}
}

func (h *Handler) move_sideways(leftwards bool) {
	r := h.state.last_render
	if r.num_matches > 0 && r.num_per_column > 0 {
		cidx := h.state.CurrentIndex()
		slots := r.num_of_slots
		if leftwards {
			idx := h.result_manager.scorer.sorted_results.IncrementIndexWithWrapAround(cidx, -slots)
			if idx.Less(cidx) {
				h.state.SetCurrentIndex(idx)
				if r.num_columns > 1 && r.num_before >= r.num_per_column {
					h.state.last_render.num_before = max(0, h.state.last_render.num_before-slots)
				}
			}
		} else {
			idx := h.result_manager.scorer.sorted_results.IncrementIndexWithWrapAround(cidx, slots)
			if cidx.Less(idx) {
				h.state.SetCurrentIndex(idx)
				if r.num_columns > 1 && r.num_before < (r.num_columns-1)*r.num_per_column {
					h.state.last_render.num_before = max(0, h.state.last_render.num_before+slots)
				}
			}
		}
	}
}
