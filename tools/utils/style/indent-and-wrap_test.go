// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestFormatWithIndent(t *testing.T) {

	screen_width := 0
	opts := WrapOptions{}

	tx := func(text string, expected ...string) {
		q := opts.Indent + strings.Join(expected, "")
		actual := WrapText(text, screen_width, opts)
		if actual != q {
			os, _ := json.Marshal(opts)
			t.Fatalf("\nFailed for: %#v\nOptions: %s\nexpected: %#v\nactual:   %#v", text, os, q, actual)
		}
	}

	opts.Indent = ""
	screen_width = 4
	tx("one two", "one \ntwo")
	tx("a  b", "a  b")
	screen_width = 3
	tx("one tw", "one\n tw")

	screen_width = 4
	opts.Trim_whitespace = true
	opts.Indent = "X"
	tx("one two", "one\nXtwo")
	tx("\x1b[2mone \x1b[mtwo", "\x1b[2mone\n\x1b[222mX\x1b[2m\x1b[mtwo")
	screen_width = 3
	tx("on tw", "on\nXtw")
	opts.Indent = ""
	opts.Trim_whitespace = false

	opts.Indent = "__"
	screen_width = 11
	tx("testing\n\ntwo", "testing\n\n__two")
	tx("testing\n \ntwo", "testing\n__ \n__two")
	a := strings.Repeat("a", screen_width-len(opts.Indent)-1)
	tx(a+" b", a+" \n__b")

	tx("123456 \x1b[31m789a", "123456 \n__\x1b[31m789a")
	tx("12 \x1b[31m789 abcd", "12 \x1b[31m789 \n\x1b[39m__\x1b[31mabcd")
	tx("bb \x1b]8;;http://xyz.com\x1b\\text\x1b]8;;\x1b\\ two", "bb \x1b]8;;http://xyz.com\x1b\\text\x1b]8;;\x1b\\ \n__two")
	tx("\x1b[31maaaaaa \x1b[39mbbbbbb", "\x1b[31maaaaaa \n\x1b[39m__\x1b[31m\x1b[39mbbbbbb")
	tx(
		"\x1b[31;4:3m\x1b]8;;XXX\x1b\\combined using\x1b]8;;\x1b\\ operators",
		"\x1b[31;4:3m\x1b]8;;XXX\x1b\\combined \n\x1b[4:0;39m\x1b]8;;\x1b\\__\x1b[4:3;31m\x1b]8;;XXX\x1b\\using\x1b]8;;\x1b\\ \n\x1b[4:0;39m__\x1b[4:3;31moperators")

	opts.Indent = ""
	screen_width = 3
	tx("one", "one")
	tx("four", "fou\nr")
	tx("nl\n\n", "nl\n\n")
	tx("four\n\n", "fou\nr\n\n")

	screen_width = 8
	tx(
		"\x1b[1mbold\x1b[221m no more bold",
		"\x1b[1mbold\x1b[221m no \nmore \nbold",
	)
}
