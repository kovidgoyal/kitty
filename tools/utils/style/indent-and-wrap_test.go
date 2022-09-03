// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"strings"
	"testing"
)

func TestFormatWithIndent(t *testing.T) {
	indent := "__"
	screen_width := 11

	tx := func(text string, expected ...string) {
		q := indent + strings.Join(expected, "") + "\n"
		actual := WrapText(text, indent, screen_width)
		if actual != q {
			t.Fatalf("%#v\nexpected: %#v\nactual:   %#v", text, q, actual)
		}
	}
	tx("testing\n\ntwo", "testing\n\n__two")
	tx("testing\n \ntwo", "testing\n\n__two")

	tx("123456 \x1b[31m789a", "123456\x1b[31m\n\x1b[39m__\x1b[31m789a")
	tx("12 \x1b[31m789 abcd", "12 \x1b[31m789\n\x1b[39m__\x1b[31mabcd")
}
