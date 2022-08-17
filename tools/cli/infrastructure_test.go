package cli

import (
	"strings"
	"testing"
)

func TestFormatWithIndent(t *testing.T) {
	var output strings.Builder
	indent := "__"
	screen_width := 11

	run := func(text string, expected ...string) {
		output.Reset()
		q := indent + strings.Join(expected, "\n"+indent) + "\n"
		format_with_indent(&output, text, indent, screen_width)
		if output.String() != q {
			t.Fatalf("expected != actual: %#v != %#v", q, output.String())
		}
	}
	run("testing \x1b[31mstyled\x1b[m", "testing ", "\x1b[31mstyled\x1b[m")
	run("testing\n\ntwo", "testing", "", "two")
	run("testing\n \ntwo", "testing", "", "two")
}
