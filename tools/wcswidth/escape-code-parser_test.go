// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package wcswidth

import (
	"testing"
)

func TestEscapeCodeParsing(t *testing.T) {
	type test_parse_collection struct {
		actual, expected string
	}
	var d test_parse_collection

	add := func(prefix string, b []byte) error {
		d.actual += "\n" + prefix + ": " + string(b)
		return nil
	}

	var test_parser = EscapeCodeParser{
		HandleCSI:  func(b []byte) error { return add("CSI", b) },
		HandleOSC:  func(b []byte) error { return add("OSC", b) },
		HandleDCS:  func(b []byte) error { return add("DCS", b) },
		HandleSOS:  func(b []byte) error { return add("SOS", b) },
		HandlePM:   func(b []byte) error { return add("PM", b) },
		HandleAPC:  func(b []byte) error { return add("APC", b) },
		HandleRune: func(b rune) error { return add("CH", []byte(string(b))) },
	}

	reset_test_parser := func() {
		test_parser.Reset()
		d = test_parse_collection{}
	}

	check_test_result := func(raw string) {
		if d.actual != d.expected {
			t.Fatalf("parsing: %#v actual != expected: %#v != %#v", raw, string(d.actual), string(d.expected))
		}
	}

	test := func(raw string, expected string) {
		reset_test_parser()
		d.expected = "\n" + expected
		test_parser.Parse([]byte(raw))
		check_test_result(raw)
	}

	test("\x1b[31m\xc2\x9bm", "CSI: 31m\nCSI: m")
	test("\x1b[-31m\xc2\x9bm", "CSI: -31m\nCSI: m")
	test("ab\nc", "CH: a\nCH: b\nCH: \n\nCH: c")
	test("a\x1b[200m\x1b[mb\x1b[5:3;2;4~", "CH: a\nCSI: 200m\nCSI: m\nCH: b\nCSI: 5:3;2;4~")
	test("\x1b[200~a\x1b[201m\x1b[201~\x1b[x", "CH: a\nCH: \x1b\nCH: [\nCH: 2\nCH: 0\nCH: 1\nCH: m\nCSI: x")
	test("a\x1bPb\x1b\x1bc\x1b\\d", "CH: a\nDCS: b\x1bc\nCH: d")
	test("a\x1b_b\x1b\x1b\x1bc\x1b\\d", "CH: a\nAPC: b\x1b\x1bc\nCH: d")
	test("\x1b]X\x07\x1b]X\x1b\x07\x1b\\", "OSC: X\nOSC: X\x1b\x07")

}
