package choose_files

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

func (h *Handler) draw_frame(width, height int, in_progress bool) {
	lp := h.lp
	prefix, suffix := "", ""
	if in_progress {
		x := h.lp.SprintStyled("fg=cyan", " ")
		prefix, suffix, _ = strings.Cut(x, " ")
		lp.QueueWriteString(prefix)
	}
	for i := range height {
		lp.SaveCursorPosition()
		switch i {
		case 0:
			lp.QueueWriteString("╭")
			lp.QueueWriteString(strings.Repeat("─", width-2))
			lp.QueueWriteString("╮")
		case height - 1:
			lp.QueueWriteString("╰")
			lp.QueueWriteString(strings.Repeat("─", width-2))
			lp.QueueWriteString("╯")
		default:
			lp.QueueWriteString("│")
			lp.MoveCursorHorizontally(width - 2)
			lp.QueueWriteString("│")
		}
		lp.RestoreCursorPosition()
		lp.MoveCursorVertically(1)
	}
	if suffix != "" {
		lp.QueueWriteString(suffix)
	}
}

func (h *Handler) draw_search_text(available_width int) {
	text := h.state.SearchText()
	available_width /= 2
	if wcswidth.Stringwidth(text) > available_width {
		g := wcswidth.SplitIntoGraphemes(text)
		available_width -= 2
		g = g[len(g)-available_width:]
		text = "…" + strings.Join(g, "")
	}
	h.lp.DrawSizedText(text+" ", loop.SizedText{Scale: 2})
	h.lp.MoveCursorHorizontally(-2)
}

const SEARCH_BAR_HEIGHT = 4

func (h *Handler) draw_controls(y int) (max_width int) {
	type entry struct {
		text     string
		callback func()
		width    int
	}
	lines := make([]entry, 0, SEARCH_BAR_HEIGHT)
	add_control := func(icon, text string, callback func()) {
		line := icon + " " + text
		width := wcswidth.Stringwidth(line)
		max_width = max(max_width, width)
		lines = append(lines, entry{line, callback, width})
	}
	add_control(utils.IfElse(h.state.ShowHidden(), " ", " "), utils.IfElse(h.state.ShowHidden(), "hide dotfiles", "show dotfiles"), func() {
		h.state.show_hidden = !h.state.show_hidden
		h.result_manager.set_show_hidden()
	})
	add_control("󰑑 ", utils.IfElse(h.state.RespectIgnores(), "show ignored", "hide ignored"), func() {
		h.state.respect_ignores = !h.state.respect_ignores
		h.result_manager.set_respect_ignores()
	})
	add_control(" ", utils.IfElse(h.state.ShowPreview(), "hide preview", "show preview"), func() {
		h.state.show_preview = !h.state.show_preview
	})
	add_control(utils.IfElse(h.state.SortByLastModified(), " ", " "), utils.IfElse(h.state.SortByLastModified(), "sort names", "sort dates"), func() {
		h.state.sort_by_last_modified = !h.state.sort_by_last_modified
		h.result_manager.set_sort_by_last_modified()
	})
	x := h.screen_size.width - max_width
	for i, e := range lines {
		h.lp.MoveCursorTo(x+1, y+i+1)
		h.lp.QueueWriteString(e.text)
		cb := e.callback
		h.state.mouse_state.AddCellRegion("rcontrol-"+strconv.Itoa(i), x, y+i, x+e.width, y+i, func(_ string) error {
			cb()
			h.state.redraw_needed = true
			return nil
		}).HoverStyle = HOVER_STYLE
	}
	return max_width + 1
}

func (h *Handler) draw_search_bar(y int) {
	left_margin, right_margin := 0, h.draw_controls(y)
	h.lp.MoveCursorTo(1+left_margin, 1+y)
	available_width := h.screen_size.width - left_margin - right_margin
	h.draw_frame(available_width, SEARCH_BAR_HEIGHT, false)
	for y1 := y; y1 < y+4; y1++ {
		cr := h.state.mouse_state.AddCellRegion("search-bar", left_margin, y1, left_margin+available_width, y1)
		cr.PointerShape = loop.TEXT_POINTER
		cr.HoverStyle = "none"
	}
	h.lp.MoveCursorTo(1+left_margin+1, 2+y)
	h.draw_search_text(available_width - 2)
}

func (h *Handler) handle_edit_keys(ev *loop.KeyEvent) bool {
	switch {
	case ev.MatchesPressOrRepeat("backspace"):
		if h.state.SearchText() == "" {
			h.lp.Beep()
		} else {
			g := wcswidth.SplitIntoGraphemes(h.state.search_text)
			h.set_query(strings.Join(g[:len(g)-1], ""))
			return true
		}
	}
	return false
}
