package tui

import (
	"fmt"
	"regexp"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print
var _ = utils.Repr

const KittyInternalHyperlinkProtocol = "kitty-ih"

func InternalHyperlink(text, id string) string {
	return fmt.Sprintf("\x1b]8;;%s:%s\x1b\\%s\x1b]8;;\x1b\\", KittyInternalHyperlinkProtocol, id, text)
}

type RenderLines struct {
}

var hyperlink_pat = sync.OnceValue(func() *regexp.Regexp {
	return regexp.MustCompile("\x1b]8;([^;]*);(.*?)(?:\x1b\\\\|\a)")
})

// Render lines in the specified rectangle. If width > 0 then lines are wrapped
// to fit in the width. A string containing rendered lines with escape codes to
// move cursor is returned. Any internal hyperlinks are added to the
// MouseState.
func (r RenderLines) InRectangle(
	lines []string, start_x, start_y, width, height int, mouse_state *MouseState, on_click ...func(id string) error,
) (all_rendered bool, y_after_last_line int, ans string) {
	end_y := start_y + height - 1
	if end_y < start_y {
		return len(lines) == 0, start_y + 1, ""
	}
	x, y := start_x, start_y
	buf := strings.Builder{}
	buf.Grow(len(lines) * max(1, width) * 3)
	move_cursor := func(x, y int) { buf.WriteString(fmt.Sprintf(loop.MoveCursorToTemplate, y+1, x+1)) }
	var hyperlink_state struct {
		action           string
		start_x, start_y int
	}

	start_hyperlink := func(action string) {
		hyperlink_state.action = action
		hyperlink_state.start_x, hyperlink_state.start_y = x, y
	}

	add_chunk := func(text string) {
		if text != "" {
			buf.WriteString(text)
			x += wcswidth.Stringwidth(text)
		}
	}

	commit_hyperlink := func() bool {
		if hyperlink_state.action == "" {
			return false
		}
		if y == hyperlink_state.start_y && x <= hyperlink_state.start_x {
			return false
		}
		mouse_state.AddCellRegion(hyperlink_state.action, hyperlink_state.start_x, hyperlink_state.start_y, max(0, x-1), y, on_click...)
		hyperlink_state.action = ``
		return true
	}

	add_hyperlink := func(id, url string) {
		is_closer := id == "" && url == ""
		if is_closer {
			if !commit_hyperlink() {
				buf.WriteString("\x1b]8;;\x1b\\")
			}
		} else {
			commit_hyperlink()
			if strings.HasPrefix(url, KittyInternalHyperlinkProtocol+":") {
				start_hyperlink(url[len(KittyInternalHyperlinkProtocol)+1:])
			} else {
				buf.WriteString(fmt.Sprintf("\x1b]8;%s;%s\x1b\\", id, url))
			}
		}

	}

	add_line := func(line string) {
		x = start_x
		indices := hyperlink_pat().FindAllStringSubmatchIndex(line, -1)
		start := 0
		for _, index := range indices {
			full_hyperlink_start, full_hyperlink_end := index[0], index[1]
			add_chunk(line[start:full_hyperlink_start])
			start = full_hyperlink_end
			add_hyperlink(line[index[2]:index[3]], line[index[4]:index[5]])
		}
		add_chunk(line[start:])
	}

	all_rendered = true
	wo := style.WrapOptions{Trim_whitespace: true}
	for _, line := range lines {
		wrapped_lines := []string{line}
		if width > 0 {
			wrapped_lines = style.WrapTextAsLines(line, width, wo)
		}
		for _, line := range wrapped_lines {
			move_cursor(start_x, y)
			add_line(line)
			y += 1
			if y > end_y {
				all_rendered = false
				goto end
			}
		}
	}
end:
	commit_hyperlink()
	return all_rendered, y, buf.String()
}
