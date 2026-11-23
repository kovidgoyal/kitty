// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/kovidgoyal/kitty/tools/utils"
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
		if consumed := color.from_params(params); consumed != min(len(params), 1) || color != initial {
			t.Fatalf("incomplete extended color %v changed the current color to %+v", params, color)
		}
	}
}

func TestWrapTextWithEmptyColorParams(t *testing.T) {
	for _, tc := range []struct{ params, color string }{
		{"38;5;", "31"},
		{"38;2;1;2;", "31"},
		{"38:2::1:2", "31"},
		{"38:2:::1:2:3", "38:2:1:2:3"},
		{"38:5::200", "38:5:200"},
		{"38;5;;", "30"},
		{"38;5;200;38:5:;", "30"},
	} {
		t.Run(tc.params, func(t *testing.T) {
			text := "\x1b[31m\x1b[" + tc.params + "mone two"
			lines := WrapTextAsLines(text, 4, WrapOptions{})
			want := "\x1b[39m\x1b[" + tc.color + "mtwo"
			if len(lines) != 2 || lines[1] != want {
				t.Fatalf("expected continuation line %q, got lines %q", want, lines)
			}
		})
	}
}

func TestSGRStateParsing(t *testing.T) {
	for raw, expected := range map[string]string{
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
		// invalid characters cause the whole code to be ignored
		"1;38;5;x;3m": "",
		"1;38:5:x;3m": "",
		"?1m":         "",
		">4;1m":       "",
		"1 m":         "",
		"1-m":         "",
		"-m":          "",
		// empty parameters terminated by a semicolon are zero, i.e. reset
		";m":             "",
		";1m":            "1",
		"1;;3m":          "3",
		"1;38;5;200;;3m": "3",
		"1;38;5;;m":      "1;30",
		"38;5;;1m":       "1;30",
		// empty parameters terminated by a colon or the end are dropped
		"1;38;5;m":     "1",
		"1;38;2;1;2;m": "1",
		"38:5::200m":   "38:5:200",
		"1;4:m":        "1;4:1",
		// empty sub-parameters terminated by a semicolon are zero
		"4:;31m":       "31",
		"4:3;38:5:;1m": "1;4:3;30",
		// a leading colon makes the code invalid
		":m":  "",
		"::m": "",
		// parameters are truncated to 16 digits and wrap at 32 bits
		"4294967299m":          "3",
		"1;00000000000000003m": "",
		// negative parameters
		"-5m":           "",
		"-;3m":          "3",
		"4:-3m":         "4:5",
		"4:-8m":         "",
		"4:-1m":         "",
		"1;221m":        "",
		"2;222m":        "",
		"1;;:3m":        "",
		"58:2::1:2:3m":  "58:2:1:2:3",
		"38;2;1;2;3;4m": "4:1;38:2:1:2:3",
		// underline styles
		"4:3m":    "4:3",
		"4:9m":    "4:5",
		"21m":     "4:2",
		"4:3;24m": "",
		"4;4:0m":  "",
		// sub-parameters of plain attributes are ignored
		"1:2m": "1",
		// misplaced sub-parameters discard the rest of the code
		":1m":           "",
		"3;38;5;1:2;1m": "3;31",
		// colon and semicolon forms can be mixed
		"38;:5;1;3m":  "1;3",
		"38;5:200;1m": "1;38:5:200",
		"38:5;200;1m": "1",
		// out of range color indices wrap
		"38;5;256m": "30",
		"38;5;-1m":  "38:5:255",
		// sub-parameters after a color are not part of it
		"38;2;1;2;3:4;1m": "38:2:1:2:3",
	} {
		var s sgr_state
		s.apply_csi(raw)
		if actual := s.as_sgr(false); actual != expected {
			t.Fatalf("Parsing SGR %q gave %q expected %q", raw, actual, expected)
		}
	}
	// Codes with more than the maximum number of parameters are ignored
	for _, n := range []int{max_csi_params, max_csi_params + 1} {
		raw := strings.Repeat("1;", n-1) + "3m"
		var s sgr_state
		s.apply_csi(raw)
		expected := utils.IfElse(n > max_csi_params, "", "1;3")
		if actual := s.as_sgr(false); actual != expected {
			t.Fatalf("Parsing SGR with %d parameters gave %q expected %q", n, actual, expected)
		}
	}
}
