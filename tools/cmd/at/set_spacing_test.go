// License: GPLv3 Copyright: 2026, kitty contributors

package at

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestParseSetSpacing(t *testing.T) {
	for args, expected := range map[string]map[string]any{
		"margin-horizontal=1": {"margin-left": 1.0, "margin-right": 1.0},
		"padding-vertical=2":  {"padding-top": 2.0, "padding-bottom": 2.0},
	} {
		actual, err := parse_set_spacing([]string{args})
		if err != nil {
			t.Fatalf("parse_set_spacing(%#v) failed with error: %s", args, err)
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("parse_set_spacing(%#v) failed:\n%s", args, diff)
		}
	}
}
