// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"testing"
)

var _ = fmt.Print

func TestLongestCommon(t *testing.T) {
	p := func(expected string, items ...string) {
		actual := Prefix(items)
		if actual != expected {
			t.Fatalf("Failed with %#v\nExpected: %#v\nActual:   %#v", items, expected, actual)
		}
	}
	p("abc", "abc", "abcd")
	p("", "abc", "xy")
}
