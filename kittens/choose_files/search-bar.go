package choose_files

import (
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

func (h *Handler) draw_frame(width, height int) {
	lp := h.lp
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

func (h *Handler) draw_search_bar(y int) {
	left_margin, right_margin := 5, 5
	h.lp.MoveCursorTo(1+left_margin, 1+y)
	available_width := h.screen_size.width - left_margin - right_margin
	h.draw_frame(available_width, SEARCH_BAR_HEIGHT)
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
			h.state.SetSearchText(strings.Join(g[:len(g)-1], ""))
			h.result_manager.set_query(h.state.SearchText())
			return true
		}
	}
	return false
}
