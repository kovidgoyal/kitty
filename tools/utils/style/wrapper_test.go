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

	test("", "", "")
	test("bold", "\x1b[1m", "\x1b[22m")
	test("bold fg=red u=curly", "\x1b[1;4:3;31m", "\x1b[22;4:0;39m")
	test("fg=123", "\x1b[38:5:123m", "\x1b[39m")
	test("fg=15", "\x1b[97m", "\x1b[39m")
	test("bg=15", "\x1b[107m", "\x1b[49m")
	test("fg=#123", "\x1b[38:2:17:34:51m", "\x1b[39m")
	test("fg=rgb:1/2/3", "\x1b[38:2:1:2:3m", "\x1b[39m")
	test("bg=123", "\x1b[48:5:123m", "\x1b[49m")
	test("uc=123", "\x1b[58:2:135:255:255m", "\x1b[59m")

	test("url=123", "\x1b]8;;123\x1b\\", "\x1b]8;;\x1b\\")
}
