// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"strings"
)

var _ = fmt.Print

// Quotes arbitrary strings for bash, dash and zsh
func QuoteStringForSH(x string) string {
	parts := strings.Split(x, "'")
	for i, p := range parts {
		parts[i] = "'" + p + "'"
	}
	return strings.Join(parts, "\"'\"")
}

// Quotes arbitrary strings for fish
func QuoteStringForFish(x string) string {
	x = strings.ReplaceAll(x, "\\", "\\\\")
	x = strings.ReplaceAll(x, "'", "\\'")
	return "'" + x + "'"
}

// Escapes common shell meta characters
func EscapeSHMetaCharacters(x string) string {
	ans := strings.Builder{}
	ans.Grow(len(x) + 32)
	for _, ch := range x {
		switch ch {
		case '\\', '|', '&', ';', '<', '>', '(', ')', '$', '\'', '"', ' ', '\n', '\t':
			ans.WriteRune('\\')
		}
		ans.WriteRune(ch)
	}
	return ans.String()
}
