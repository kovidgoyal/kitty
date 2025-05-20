package choose_files

import (
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
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

func (h *Handler) draw_search_text() {
	text := h.state.SearchText()
	if text == "" {
		h.lp.DrawSizedText(" ", loop.SizedText{Scale: 2})
		h.lp.MoveCursorHorizontally(-2)
		return
	}
}

func (h *Handler) draw_search_bar(y int) (height int, err error) {
	left_margin, right_margin := 5, 5
	height = 4
	h.lp.MoveCursorTo(1+left_margin, 1+y)
	available_width := h.screen_size.width - left_margin - right_margin
	h.draw_frame(available_width, height)
	h.lp.MoveCursorTo(1+left_margin+1, 2+y)
	h.draw_search_text()

	return
}
