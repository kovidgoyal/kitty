// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"os"
	"sync"

	"github.com/kovidgoyal/kitty/tools/highlight"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
)

var _ = fmt.Print
var _ = os.WriteFile

type prefer_light_colors bool

func (s prefer_light_colors) StyleName() string {
	return utils.IfElse(bool(s), conf.Pygments_style, conf.Dark_pygments_style)
}

func (s prefer_light_colors) UseLightColors() bool                    { return bool(s) }
func (s prefer_light_colors) SyntaxAliases() map[string]string        { return conf.Syntax_aliases }
func (s prefer_light_colors) TextForPath(path string) (string, error) { return data_for_path(path) }

var highlighter = sync.OnceValue(func() highlight.Highlighter {
	return highlight.NewHighlighter(sanitize)
})

func highlight_all(paths []string, light bool) {
	ctx := images.Context{}
	srd := prefer_light_colors(light)
	ctx.Parallel(0, len(paths), func(nums <-chan int) {
		for i := range nums {
			path := paths[i]
			raw, err := highlighter().HighlightFile(path, &srd)
			if err != nil {
				continue
			}
			if light {
				light_highlighted_lines_cache.Set(path, text_to_lines(raw))
			} else {
				dark_highlighted_lines_cache.Set(path, text_to_lines(raw))
			}
		}
	})
}
