// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"bufio"
	"fmt"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestStringScanner(t *testing.T) {
	for _, text := range []string{
		"a\nb\nc",
		"a\nb\nc\r",
		"a\n\n\nb\nc",
		"a\r\r\nb\r\nc\n",
		"\n1",
		"",
		"\n",
	} {
		actual := Splitlines(text)
		expected := make([]string, 0, len(actual))
		s := bufio.NewScanner(strings.NewReader(text))
		for s.Scan() {
			expected = append(expected, s.Text())
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed for: %#v\n%s", text, diff)
		}
	}
}

func TestReplaceControlCodes(t *testing.T) {
	for text, expected := range map[string]string{
		"none":                    "none",
		"a\r\x01b\x03\x7f c\n\td": "a\u240d\u2401b\u2403\u2421 cX  d",
		"\x01":                    "\u2401",
		"\x00\x0b":                "\u2400\u240b",
	} {
		actual := ReplaceControlCodes(text, "  ", "X")
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed for text: %#v\n%s", text, diff)
		}
	}
}
