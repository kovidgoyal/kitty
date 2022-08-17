package cli

import (
	"strings"
	"testing"
)

func TestFormatLineWithIndent(t *testing.T) {
	var output strings.Builder

	output.Reset()
	indent := "  "
	format_line_with_indent(&output, "testing \x1b[31mstyled\x1b[m", indent, 11)
	expected := indent + "testing \n" + indent + "\x1b[31mstyled\x1b[m\n"
	if output.String() != expected {
		t.Fatalf("%#v != %#v", expected, output.String())
	}
}
