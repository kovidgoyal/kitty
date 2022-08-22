package utils

import (
	"testing"
)

func TestEscapeCodeParsing(t *testing.T) {
	type test_parse_collection struct {
		actual, expected string
	}
	var d test_parse_collection

	add := func(prefix string, b []byte) {
		d.actual += "\n" + prefix + ": " + string(b)
	}

	var test_parser = EscapeCodeParser{
		HandleCSI:  func(b []byte) { add("CSI", b) },
		HandleOSC:  func(b []byte) { add("OSC", b) },
		HandleDCS:  func(b []byte) { add("DCS", b) },
		HandleSOS:  func(b []byte) { add("SOS", b) },
		HandlePM:   func(b []byte) { add("PM", b) },
		HandleAPC:  func(b []byte) { add("APC", b) },
		HandleRune: func(b rune) { add("CH", []byte(string(b))) },
	}

	reset_test_parser := func() {
		test_parser.Reset()
		d = test_parse_collection{}
	}

	check_test_result := func() {
		if d.actual != d.expected {
			t.Fatalf("actual != expected: %#v != %#v", string(d.actual), string(d.expected))
		}
	}

	test := func(raw string, expected string) {
		reset_test_parser()
		d.expected = "\n" + expected
		test_parser.Parse([]byte(raw))
		check_test_result()
	}

	test("\x1b[31m\xc2\x9bm", "CSI: 31m\nCSI: m")
	test("ab\nc", "CH: a\nCH: b\nCH: \n\nCH: c")
	test("a\x1b[200m\x1b[mb\x1b[5:3;2;4~", "CH: a\nCSI: 200m\nCSI: m\nCH: b\nCSI: 5:3;2;4~")

}
