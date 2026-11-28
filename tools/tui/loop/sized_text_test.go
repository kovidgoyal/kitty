// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"testing"
)

func TestSizedTextEscapeCode(t *testing.T) {
	for _, tc := range []struct {
		spec     SizedText
		expected string
	}{
		{SizedText{}, "\x1b]66;;A\a"},
		{SizedText{Scale: 2}, "\x1b]66;s=2;A\a"},
		{SizedText{Scale: 9, Width: 9}, "\x1b]66;s=7:w=7;A\a"},
		{SizedText{Subscale_numerator: 1, Subscale_denominator: 2, Vertical_alignment: 2, Width: 1}, "\x1b]66;w=1:n=1:d=2:v=2;A\a"},
		{SizedText{Scale: 2, Width: 1, Part_y: 1, Part_rows: 1}, "\x1b]66;s=2:w=1:y=1:r=1;A\a"},
		{SizedText{Width: 2, Part_x: 1, Part_columns: 1}, "\x1b]66;w=2:x=1:c=1;A\a"},
	} {
		if actual := SizedTextEscapeCode("A", tc.spec); actual != tc.expected {
			t.Fatalf("Escape code for %#v: %q != %q", tc.spec, actual, tc.expected)
		}
	}
}

func TestTextSizingPartsQuery(t *testing.T) {
	for _, tc := range []struct {
		replies   []string
		supported bool
	}{
		{[]string{"?3;1R", "?3;2R"}, true},
		{[]string{"?3;1R", "?3;1R"}, false},
		{[]string{"?3;1R", "?3;3R"}, false},
		{[]string{"?3;1;1R", "?3;2;1R"}, true},
	} {
		q := TextSizingPartsQuery{}
		for i, r := range tc.replies {
			if !q.HandleEscapeCode(CSI, []byte(r)) {
				t.Fatalf("Reply not handled: %q", r)
			}
			if q.Done != (i == len(tc.replies)-1) {
				t.Fatalf("Incorrect done state after %q: %v", r, q.Done)
			}
		}
		if q.Supported != tc.supported {
			t.Fatalf("Incorrect support for %v: %v", tc.replies, q.Supported)
		}
		if q.HandleEscapeCode(CSI, []byte("?3;2R")) {
			t.Fatalf("Reply handled after the query was done")
		}
	}
	q := TextSizingPartsQuery{}
	for _, r := range []string{"3;1R", "?3R", "1;5u", "?1u"} {
		if q.HandleEscapeCode(CSI, []byte(r)) {
			t.Fatalf("Escape code that is not a reply handled: %q", r)
		}
	}
	if q.HandleEscapeCode(OSC, []byte("?3;1R")) {
		t.Fatalf("OSC escape code handled")
	}
}
