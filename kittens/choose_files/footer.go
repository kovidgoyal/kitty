package choose_files

import (
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type single_line_region struct {
	x, width, y int
	id          string
	callback    func(string) error
}

func (h *Handler) draw_footer() (num_lines int, err error) {
	lines := []string{}
	screen_width := h.screen_size.width
	sctx := style.Context{AllowEscapeCodes: true}
	if len(h.state.filter_map) > 0 {
		buf := strings.Builder{}
		pos := 0
		current_style := sctx.SprintFunc("italic fg=green intense")
		non_current_style := sctx.SprintFunc("dim")
		var crs []single_line_region
		w := func(presep, text string, sfunc func(...any) string, click_name string) {
			sz := len(presep)
			if sz+pos >= screen_width {
				lines = append(lines, buf.String())
				pos = 0
				buf.Reset()
			}
			buf.WriteString(presep)
			pos += sz
			sz = wcswidth.Stringwidth(text)
			if sfunc != nil {
				text = sfunc(text)
			}
			buf.WriteString(text)
			if click_name != "" && click_name != h.state.current_filter {
				crs = append(crs, single_line_region{x: pos, width: sz - 1, y: len(lines), id: click_name, callback: func(filter string) error {
					h.set_filter(filter)
					h.state.redraw_needed = true
					return nil
				}})
			}
			pos += sz
		}
		w("", "󰈲 Filter:", nil, "")
		for _, name := range h.state.filter_names {
			w("  ", name, utils.IfElse(name == h.state.current_filter, current_style, non_current_style), name)
		}
		if s := buf.String(); s != "" {
			lines = append(lines, s)
		}
		offset := h.screen_size.height - len(lines)
		for _, cr := range crs {
			h.state.mouse_state.AddCellRegion(cr.id, cr.x, cr.y+offset, cr.x+cr.width, cr.y+offset, cr.callback).HoverStyle = "default fg=red"
		}
	}
	if len(lines) > 0 {
		h.lp.MoveCursorTo(1, h.screen_size.height-len(lines)+1)
		h.lp.QueueWriteString(strings.Join(lines, "\r\n"))
	}
	return len(lines), err
}
