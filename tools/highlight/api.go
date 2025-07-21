package highlight

import (
	"errors"
	"fmt"

	"github.com/alecthomas/chroma/v2"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

var ErrNoLexer = errors.New("No lexer available for this format")

type StyleResolveData interface {
	StyleName() string
	UseLightColors() bool
	SyntaxAliases() map[string]string
	TextForPath(string) (string, error)
}

type Highlighter interface {
	HighlightFile(path string, srd StyleResolveData) (highlighted_string string, err error)
	Sanitize(string) string
}

func NewHighlighter(sanitize func(string) string) Highlighter {
	if sanitize == nil {
		sanitize = func(text string) string { return utils.ReplaceControlCodes(text, "    ", "\n") }
	}
	return &highlighter{sanitize: sanitize, tokens_map: make(map[string][]chroma.Token)}
}
