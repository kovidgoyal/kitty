package choose_files

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

// Actions that, when matched by a keyboard shortcut, are forwarded to the
// readline instance powering the search/filter text box instead of being
// dispatched as a normal choose_files action. This lets users who prefer
// editing text with the arrow keys, Home, End, etc. rebind those keys away
// from their default job of navigating the list of matches, towards editing
// the search text instead. See the kitten's documentation for details.
var edit_actions = map[string]readline.Action{
	"edit_cursor_left":           readline.ActionCursorLeft,
	"edit_cursor_right":          readline.ActionCursorRight,
	"edit_start_of_line":         readline.ActionMoveToStartOfLine,
	"edit_end_of_line":           readline.ActionMoveToEndOfLine,
	"edit_start_of_document":     readline.ActionMoveToStartOfDocument,
	"edit_end_of_document":       readline.ActionMoveToEndOfDocument,
	"edit_forward_word":          readline.ActionMoveToEndOfWord,
	"edit_backward_word":         readline.ActionMoveToStartOfWord,
	"edit_backspace":             readline.ActionBackspace,
	"edit_delete":                readline.ActionDelete,
	"edit_kill_to_start_of_line": readline.ActionKillToStartOfLine,
	"edit_kill_to_end_of_line":   readline.ActionKillToEndOfLine,
	"edit_kill_word_left":        readline.ActionKillPreviousWord,
	"edit_kill_word_right":       readline.ActionKillNextWord,
	"edit_yank":                  readline.ActionYank,
}

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
	available_width /= 2
	all_graphemes := wcswidth.SplitIntoGraphemes(h.state.SearchText())
	cursor_pos := len(wcswidth.SplitIntoGraphemes(h.search_rl.TextBeforeCursor()))
	start, end := 0, len(all_graphemes)
	left_ellipsis, right_ellipsis := false, false
	if len(all_graphemes) > available_width && available_width > 0 {
		start = cursor_pos - available_width/2
		start = max(0, start)
		end = min(len(all_graphemes), start+available_width)
		start = max(0, end-available_width)
		left_ellipsis = start > 0
		right_ellipsis = end < len(all_graphemes)
		if left_ellipsis {
			start++
		}
		if right_ellipsis {
			end--
		}
		end = max(start, end)
	}
	visible := make([]string, 0, end-start+2)
	if left_ellipsis {
		visible = append(visible, "…")
	}
	visible = append(visible, all_graphemes[start:end]...)
	if right_ellipsis {
		visible = append(visible, "…")
	}
	cursor_col := cursor_pos - start
	if left_ellipsis {
		cursor_col++
	}
	cursor_col = max(0, min(cursor_col, len(visible)))
	h.lp.DrawSizedText(strings.Join(visible, "")+" ", loop.SizedText{Scale: 2})
	h.lp.MoveCursorHorizontally(-2 * (len(visible) - cursor_col + 1))
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

// perform_edit_action runs a readline editing action against the search text
// box and syncs the resulting text back into the query used to filter results.
func (h *Handler) perform_edit_action(ac readline.Action) (err error) {
	if err = h.search_rl.PerformAction(ac, 1); err == nil {
		h.set_query(h.search_rl.AllText())
	}
	return
}

// forward_key_event_to_search_rl is used for keys that are not claimed by any
// configured keyboard shortcut, so that ordinary readline editing (backspace,
// delete, ctrl+k, ctrl+w, etc.) works in the search box without needing
// explicit configuration.
func (h *Handler) forward_key_event_to_search_rl(ev *loop.KeyEvent) (err error) {
	if err = h.search_rl.OnKeyEvent(ev); err == nil {
		h.set_query(h.search_rl.AllText())
	}
	return
}
