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
