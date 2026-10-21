// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestParseSetSpacing(t *testing.T) {
	ten := float64(10)
	for args, expected := range map[string]map[string]any{
		"padding=default": {"padding-left": nil, "padding-top": nil, "padding-right": nil, "padding-bottom": nil},
		"margin-h=10":     {"margin-left": ten, "margin-right": ten},
		"Margin-Horizontal=10 padding-vertical=default": {"margin-left": ten, "margin-right": ten, "padding-top": nil, "padding-bottom": nil},
		"padding-v=10 margin-bottom=10":                 {"padding-top": ten, "padding-bottom": ten, "margin-bottom": ten},
	} {
		actual, err := parse_set_spacing(strings.Fields(args))
		if err != nil {
			t.Fatalf("parse_set_spacing(%#v) failed with error: %s", args, err)
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("parse_set_spacing(%#v) returned unexpected result:\n%s", args, diff)
		}
	}
	for _, arg := range []string{"margin", "margin-diagonal=10", "padding=x"} {
		if actual, err := parse_set_spacing([]string{arg}); err == nil {
			t.Fatalf("parse_set_spacing(%#v) accepted invalid input and returned: %v", arg, actual)
		}
	}
}
