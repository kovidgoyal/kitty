// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"fmt"
	"testing"
)

var _ = fmt.Print

func TestANSIStyleContext(t *testing.T) {
	var ctx = Context{AllowEscapeCodes: false}
	sprint := ctx.SprintFunc("bold")
	if sprint("test") != "test" {
		t.Fatal("AllowEscapeCodes=false not respected")
	}
	ctx.AllowEscapeCodes = true
	if sprint("test") == "test" {
		t.Fatal("AllowEscapeCodes=true not respected")
	}
}

func TestANSIStyleSprint(t *testing.T) {
	var ctx = Context{AllowEscapeCodes: true}

	test := func(spec string, prefix string, suffix string) {
		actual := ctx.SprintFunc(spec)("  ")
		expected := prefix + "  " + suffix
		if actual != expected {
			t.Fatalf("Formatting with spec: %s failed expected != actual: %#v != %#v", spec, expected, actual)
		}
	}

	test("bold", "\x1b[1m", "\x1b[22m")
	test("bold fg=red u=curly", "\x1b[1;4:3;31m", "\x1b[22;4:0;39m")

}
