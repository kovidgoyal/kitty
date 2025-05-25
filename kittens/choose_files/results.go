package choose_files

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/icons"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

func (h *Handler) draw_results_title() {
	text := filepath.Clean(h.state.BaseDir())
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
	text = fmt.Sprintf(" %s %s ", h.lp.SprintStyled("fg=blue", string(icons.FOLDER)+" "), h.lp.SprintStyled("fg=intense-white bold", text))
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

func icon_for(path string, x os.DirEntry) string {
	if icon_cache == nil {
		icon_cache = make(map[string]string, 512)
	}
	if ans := icon_cache[path]; ans != "" {
		return ans
	}
	ans := icons.IconForFileWithMode(path, x.Type(), true)
	if wcswidth.Stringwidth(ans) == 1 {
		ans += " "
	}
	icon_cache[path] = ans
	return ans
}

func (h *Handler) draw_column_of_matches(matches []*ResultItem, current_idx int, x, available_width, num_before, num_after int) {
	if num_before > 0 {
		h.lp.QueueWriteString("\r")
		h.lp.MoveCursorHorizontally(x)
		h.lp.QueueWriteString("…  ")
		text := h.lp.SprintStyled("italic", fmt.Sprintf("%d prev matches", num_before))
		h.render_match_with_positions(text, false, nil, false)
	}
	for i, m := range matches {
		h.lp.QueueWriteString("\r")
		h.lp.MoveCursorHorizontally(x)
		icon := icon_for(m.abspath, m.dir_entry)
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
		h.render_match_with_positions(text, add_ellipsis, m.positions, is_current)
		h.lp.MoveCursorVertically(1)
	}
	if num_after > 0 {
		h.lp.QueueWriteString("\r")
		h.lp.MoveCursorHorizontally(x)
		h.lp.QueueWriteString("…  ")
		text := h.lp.SprintStyled("italic", fmt.Sprintf("%d more matches", num_after))
		h.render_match_with_positions(text, false, nil, false)
	}
}

func (h *Handler) draw_list_of_results(matches []*ResultItem, y, height int) {
	if len(matches) == 0 || height < 2 {
		return
	}
	available_width := h.screen_size.width - 2
	col_width := available_width
	num_cols := 1
	if len(matches) > height {
		col_width = 40
		num_cols = available_width / col_width
		for num_cols > 0 && height*(num_cols-1) >= len(matches) {
			num_cols--
		}
		col_width = available_width / num_cols
	}
	num_that_can_be_displayed := num_cols * height
	num_after, num_before := 0, 0
	idx := min(h.state.CurrentIndex(), len(matches)-1)
	if idx == 0 {
		num_after = max(0, len(matches)-num_that_can_be_displayed)
	} else {
		num_after = max(0, len(matches)-num_that_can_be_displayed)
		last_idx := len(matches) - 1 - num_after
		if last_idx < idx {
			num_before = last_idx - idx
			num_after = max(0, num_after-num_before)
		}
	}
	pos := num_before
	x := 1
	for i := range num_cols {
		is_last, is_first := i == num_cols-1, i == 0
		num := height
		if is_first && num_before > 0 {
			num--
		}
		if is_last && num_after > 0 {
			num--
		}
		h.lp.MoveCursorTo(x, y)
		limit := min(len(matches), pos+num)
		h.draw_column_of_matches(matches[pos:limit], idx-pos, x, col_width-1, num_before, utils.IfElse(is_last, len(matches)-limit, 0))
		x += col_width
		pos += num
		num_before = 0
		if pos >= len(matches) {
			break
		}
	}
}

func (h *Handler) draw_results(y, bottom_margin int, matches []*ResultItem, in_progress bool) (height int) {
	height = h.screen_size.height - y - bottom_margin
	h.lp.MoveCursorTo(1, 1+y)
	h.draw_frame(h.screen_size.width, height)
	h.lp.MoveCursorTo(1, 1+y)
	h.draw_results_title()
	y += 2
	h.lp.MoveCursorTo(1, y)
	switch len(matches) {
	case 0:
		h.draw_no_matches_message(in_progress)
	default:
		h.draw_list_of_results(matches, y, height-2)
	}
	return
}
