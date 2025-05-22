package choose_files

import (
	"fmt"
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

func (h *Handler) draw_matching_result(r ResultItem) {
	icon := icon_for(r.abspath, r.dir_entry)
	h.lp.MoveCursorHorizontally(1)
	p, s, _ := strings.Cut(h.lp.SprintStyled(matching_position_style, " "), " ")
	h.lp.QueueWriteString(p)
	h.lp.DrawSizedText(icon, loop.SizedText{Scale: 2})
	h.lp.QueueWriteString(s)
	text := r.text
	available_width := (h.screen_size.width - 6) / 2
	add_ellipsis := false
	if wcswidth.Stringwidth(text) > available_width {
		text = wcswidth.TruncateToVisualLength(text, available_width-2)
		add_ellipsis = true
	}
	h.render_match_with_positions(text, add_ellipsis, r.positions, 2)
}

func (h *Handler) render_match_with_positions(text string, add_ellipsis bool, positions []int, scale int) {
	prefix, suffix, _ := strings.Cut(h.lp.SprintStyled(matching_position_style, " "), " ")
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
		if scale > 1 {
			h.lp.DrawSizedText(text, loop.SizedText{Scale: scale})
		} else {
			h.lp.QueueWriteString(text)
		}
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

func (h *Handler) draw_column_of_matches(matches []ResultItem, x, available_width, num_extra_matches int) {
	for i, m := range matches {
		h.lp.QueueWriteString("\r")
		h.lp.MoveCursorHorizontally(x)
		icon := icon_for(m.abspath, m.dir_entry)
		text := ""
		add_ellipsis := false
		positions := m.positions
		if num_extra_matches > 0 && i == len(matches)-1 {
			icon = "… "
			text = h.lp.SprintStyled("italic", fmt.Sprintf("%d more matches", num_extra_matches))
			positions = nil
		} else {
			text = m.text
			if wcswidth.Stringwidth(text) > available_width-3 {
				text = wcswidth.TruncateToVisualLength(text, available_width-4)
				add_ellipsis = true
			}
		}
		h.lp.QueueWriteString(icon + " ")
		h.render_match_with_positions(text, add_ellipsis, positions, 1)
		h.lp.MoveCursorVertically(1)
	}
}

func (h *Handler) draw_list_of_results(matches []ResultItem, y, height int) {
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
	x := 1
	for i := range num_cols {
		is_last := i == num_cols-1
		chunk := matches[:min(len(matches), height)]
		matches = matches[len(chunk):]
		h.lp.MoveCursorTo(x, y)
		h.draw_column_of_matches(chunk, x, col_width-1, utils.IfElse(is_last, len(matches), 0))
		x += col_width
	}
}

func (h *Handler) draw_results(y, bottom_margin int, matches []ResultItem, in_progress bool) (height int) {
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
		switch h.state.SearchText() {
		case "":
			h.draw_list_of_results(matches, y, height-2)
		default:
			h.draw_matching_result(matches[0])
			y += 2
			h.draw_list_of_results(matches[1:], y, height-4)
		}
	}
	return
}
