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
	a := strings.Repeat("a", screen_width-len(indent)-1)
	tx(a+" b", a+"\n__b")

	tx("123456 \x1b[31m789a", "123456\n__\x1b[31m789a")
	tx("12 \x1b[31m789 abcd", "12 \x1b[31m789\n\x1b[39m__\x1b[31mabcd")
	tx("bb \x1b]8;;http://xyz.com\x1b\\text\x1b]8;;\x1b\\ two", "bb \x1b]8;;http://xyz.com\x1b\\text\x1b]8;;\x1b\\\n__two")
	tx("\x1b[31maaaaaa \x1b[39mbbbbbb", "\x1b[31maaaaaa\n\x1b[39m__\x1b[31m\x1b[39mbbbbbb")
	tx(
		"\x1b[31;4:3m\x1b]8;;XXX\x1b\\combined using\x1b]8;;\x1b\\ operators",
		"\x1b[31;4:3m\x1b]8;;XXX\x1b\\combined\n\x1b[4:0;39m\x1b]8;;\x1b\\__\x1b[4:3;31m\x1b]8;;XXX\x1b\\using\x1b]8;;\x1b\\\n\x1b[4:0;39m__\x1b[4:3;31moperators")

}
