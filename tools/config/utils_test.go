// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package config

import (
	"fmt"
	"testing"
)

var _ = fmt.Print

func TestStringLiteralParsing(t *testing.T) {
	for q, expected := range map[string]string{
		`abc`:                    `abc`,
		`a\nb\M`:                 "a\nb\\M",
		`a\x20\x1\u1234\123\12|`: "a \\x1\u1234\123\x0a|",
	} {
		actual, err := StringLiteral(q)
		if err != nil {
			t.Fatal(err)
		}
		if expected != actual {
			t.Fatalf("Failed with input: %#v\n%#v != %#v", q, expected, actual)
		}
	}
}
