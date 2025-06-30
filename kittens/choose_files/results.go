package choose_files

import (
	"fmt"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/icons"
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

func (h *Handler) draw_column_of_matches(matches ResultsType, current_idx int, x, available_width int) {
	root_dir := h.state.CurrentDir()
	for i, m := range matches {
		h.lp.QueueWriteString("\r")
		h.lp.MoveCursorHorizontally(x)
		icon := icon_for(filepath.Join(root_dir, m.text), m.ftype)
		text := m.text
		add_ellipsis := false
		if wcswidth.Stringwidth(text) > available_width-3 {
			text = wcswidth.TruncateToVisualLength(text, available_width-4)
			add_ellipsis = true
		}
		is_current := i == current_idx
		if is_current {
			h.lp.QueueWriteString(h.lp.SprintStyled(matching_position_style, icon+" "))
		} else {
			h.lp.QueueWriteString(icon + " ")
		}
		h.render_match_with_positions(text, add_ellipsis, m.sorted_positions(), is_current)
		h.lp.MoveCursorVertically(1)
	}
}

func (h *Handler) draw_list_of_results(matches *SortedResults, y, height int) int {
	available_width := h.screen_size.width - 2
	col_width := available_width
	num_cols := 1
	calc_num_cols := func(num_matches int) int {
		if num_matches == 0 || height < 2 {
			return 0
		}
		if num_matches > height {
			col_width = 40
			num_cols = available_width / col_width
			for num_cols > 0 && height*(num_cols-1) >= num_matches {
				num_cols--
			}
			col_width = available_width / num_cols
		}
		return num_cols
	}
	columns, num_before := matches.SplitIntoColumns(calc_num_cols, height, h.state.last_render.num_before, h.state.CurrentIndex())
	h.state.last_render.num_before = num_before
	h.state.last_render.num_per_column = height
	h.state.last_render.num_columns = num_cols
	x := 1
	for _, col := range columns {
		h.lp.MoveCursorTo(x, y)
		h.draw_column_of_matches(col, num_before, x, col_width-1)
		num_before -= height
		x += col_width
	}
	return len(columns)
}

func (h *Handler) draw_num_of_matches(num_shown, y int) {
	m := ""
	switch h.state.last_render.num_matches {
	case 0:
		m = " no matches "
	default:
		m = fmt.Sprintf(" %d of %d matches ", min(num_shown, h.state.last_render.num_matches), h.state.last_render.num_matches)
	}
	w := int(math.Ceil(float64(wcswidth.Stringwidth(m)) / 2.0))
	h.lp.MoveCursorTo(h.screen_size.width-w-2, y)
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
}

func (h *Handler) draw_results(y, bottom_margin int, matches *SortedResults, in_progress bool) (height int) {
	height = h.screen_size.height - y - bottom_margin
	h.lp.MoveCursorTo(1, 1+y)
	h.draw_frame(h.screen_size.width, height)
	h.lp.MoveCursorTo(1, 1+y)
	h.draw_results_title()
	y += 2
	h.lp.MoveCursorTo(1, y)
	h.state.last_render.num_of_slots = height - 2
	num_cols := 0
	num := matches.Len()
	switch num {
	case 0:
		h.draw_no_matches_message(in_progress)
	default:
		num_cols = h.draw_list_of_results(matches, y, h.state.last_render.num_of_slots)
	}
	h.state.last_render.num_matches = num
	h.draw_num_of_matches(h.state.last_render.num_of_slots*num_cols, y+height-2)
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

func (h *Handler) handle_result_list_keys(ev *loop.KeyEvent) bool {
	switch {
	case ev.MatchesPressOrRepeat("down"):
		h.next_result(1)
		return true
	case ev.MatchesPressOrRepeat("up"):
		h.next_result(-1)
		return true
	case ev.MatchesPressOrRepeat("left") || ev.MatchesPressOrRepeat("pgup"):
		h.move_sideways(true)
		return true
	case ev.MatchesPressOrRepeat("right") || ev.MatchesPressOrRepeat("pgdn"):
		h.move_sideways(false)
		return true
	default:
		return false
	}
}
