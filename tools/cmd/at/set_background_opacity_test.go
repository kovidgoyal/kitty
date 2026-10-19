// License: GPLv3 Copyright: 2026, kitty contributors

package at

import (
	"testing"
)

func TestParseOpacity(t *testing.T) {
	valid := map[string]float64{
		"0.5": 0.5, "0": 0, "1": 1, "2": 1, "-1": 0, "inf": 1, "-inf": 0,
	}
	for arg, expected := range valid {
		actual, err := parse_opacity(arg)
		if err != nil {
			t.Fatalf("parse_opacity(%#v) failed with error: %s", arg, err)
		}
		if actual != expected {
			t.Fatalf("parse_opacity(%#v) = %v != %v", arg, actual, expected)
		}
	}
	for _, arg := range []string{"oops", "", "nan", "NaN", "0.5x"} {
		if actual, err := parse_opacity(arg); err == nil {
			t.Fatalf("parse_opacity(%#v) accepted an invalid number and returned: %v", arg, actual)
		}
	}
}
