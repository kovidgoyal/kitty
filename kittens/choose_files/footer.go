package choose_files

import (
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

func (h *Handler) draw_footer() (num_lines int, err error) {
	lines := []string{}
	screen_width := h.screen_size.width
	sctx := style.Context{AllowEscapeCodes: true}
	if len(h.state.filter_map) > 0 {
		buf := strings.Builder{}
		pos := 0
		current_style := sctx.SprintFunc("italic fg=green intense")
		non_current_style := sctx.SprintFunc("dim")
		w := func(text string, sfunc func(...any) string) {
			sz := wcswidth.Stringwidth(text)
			if sz+pos >= screen_width {
				lines = append(lines, buf.String())
				pos = 0
				buf.Reset()
			}
			if sfunc != nil {
				text = sfunc(text)
			}
			buf.WriteString(text)
			pos += sz
		}
		w("󰈲 Filter:", nil)
		for _, name := range h.state.filter_names {
			w("  "+name, utils.IfElse(name == h.state.current_filter, current_style, non_current_style))
		}
		if s := buf.String(); s != "" {
			lines = append(lines, s)
		}
	}
	if len(lines) > 0 {
		h.lp.MoveCursorTo(1, h.screen_size.height-len(lines)+1)
		h.lp.QueueWriteString(strings.Join(lines, "\r\n"))
	}
	return len(lines), err
}
