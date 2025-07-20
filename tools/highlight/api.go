package highlight

import (
	"errors"
	"fmt"
	"strings"

	"github.com/alecthomas/chroma/v2"
)

var _ = fmt.Print

var ErrNoLexer = errors.New("No lexer available for this format")

type StyleResolveData interface {
	StyleName() string
	UseLightColors() bool
	SyntaxAliases() map[string]string
	TextForPath(string) (string, error)
}

type SanitizeControlCodes struct {
	r *strings.Replacer
}

func (s SanitizeControlCodes) Sanitize(x string) string { return s.r.Replace(x) }

func NewSanitizeControlCodes(replace_tab_by string) *SanitizeControlCodes {
	repls := make([]string, 0, 2*(0x1f+2+(0x9f-0x80+1)))
	for i := range 0x1f + 1 {
		var repl string
		switch i {
		case '\n', ' ':
			repl = string(rune(i))
		case '\t':
			repl = replace_tab_by
		default:
			repl = string(rune(0x2400 + i))
		}
		repls = append(repls, string(rune(i)), repl)
	}
	return &SanitizeControlCodes{r: strings.NewReplacer(repls...)}
}

type Highlighter interface {
	HighlightFile(path string, srd StyleResolveData) (highlighted_string string, err error)
}

func NewHighlighter(sanitize func(string) string) Highlighter {
	if sanitize == nil {
		s := NewSanitizeControlCodes("    ")
		sanitize = s.Sanitize
	}
	return &highlighter{sanitize: sanitize, tokens_map: make(map[string][]chroma.Token)}
}
