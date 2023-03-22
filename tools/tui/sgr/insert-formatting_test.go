// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package sgr

import (
	"fmt"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestInsertFormatting(t *testing.T) {
	test := func(src, expected string, spans ...*Span) {
		actual := InsertFormatting(src, spans...)
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed with %#v:\n%#v != %#v\n%s", src, expected, actual, diff)
		}
	}
	test(
		"\x1b[44m abcd \x1b[49m",
		"\x1b[44m a\x1b[33;41mbc\x1b[39;49m\x1b[44md \x1b[49m",
		NewSpan(2, 2).SetForeground(3).SetBackground(1),
	)
	test(
		"abcd",
		"a\x1b[92mbcd\x1b[39m",
		NewSpan(1, 11).SetForeground(10),
	)
}
