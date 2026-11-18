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

	screen_width = 5
	opts.Indent = "_"
	tx(
		"\x1b[38;5;200mone two",
		"\x1b[38;5;200mone \n\x1b[39m_\x1b[38:5:200mtwo",
	)
	tx(
		"\x1b[1;48;2;3;;7;58;5;180;9mone two",
		"\x1b[1;48;2;3;;7;58;5;180;9mone \n\x1b[221;29;49;59m_\x1b[1;9;48:2:3:0:7;58:5:180mtwo",
	)
	tx(
		"\x1b[38:5:200;48:2::3:4:7mone two",
		"\x1b[38:5:200;48:2::3:4:7mone \n\x1b[39;49m_\x1b[38:5:200;48:2:3:4:7mtwo",
	)
}

func TestIncompleteExtendedColor(t *testing.T) {
	initial := sgr_color{number: 201}
	for _, params := range [][]int{nil, {5}, {2, 3, 4}} {
		color := initial
		if color.from_extended(params) || color != initial {
			t.Fatalf("incomplete extended color %v changed the current color to %+v", params, color)
		}
	}
	for _, params := range [][]string{{"5"}, {"2", "3", "4"}} {
		color := initial
		if remaining := color.from_semicolon_params(params); len(remaining) != 0 || color != initial {
			t.Fatalf("incomplete extended color %q left parameters %q and color %+v", params, remaining, color)
		}
	}
}

func TestSGRStateParsing(t *testing.T) {
	for raw, expected := range map[string]string{
		// trailing empty parameters default to zero
		"38;5;m":     "30",
		"38;2;1;2;m": "38:2:1:2:0",
		// the color space id in the colon form is ignored
		"38:2:1:2:3:4m": "38:2:2:3:4",
		"38:2:1:2:3m":   "38:2:1:2:3",
		"48:2::3:4:7m":  "48:2:3:4:7",
		// bright colors round trip
		"90m":      "90",
		"97m":      "97",
		"100m":     "100",
		"107m":     "107",
		"38;5;8m":  "90",
		"38;5;15m": "97",
		"48;5;9m":  "101",
		"58;5;9m":  "58:5:9",
		"38;5;16m": "38:5:16",
		// attributes after an extended color are applied
		"38;5;200;1;3m":   "1;3;38:5:200",
		"48;2;1;2;3;4:3m": "4:3;48:2:1:2:3",
		// unknown color types discard the rest of the parameters
		"1;38;7;3m": "1",
		// invalid colors are ignored
		"38;5;x;3m": "3",
		"38:5:x;3m": "3",
	} {
		var s sgr_state
		s.apply_csi(raw)
		if actual := s.as_sgr(false); actual != expected {
			t.Fatalf("Parsing SGR %q gave %q expected %q", raw, actual, expected)
		}
	}
}
