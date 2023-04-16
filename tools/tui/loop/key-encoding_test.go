// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestKeyEventFromCSI(t *testing.T) {

	test_text := func(csi string, expected, alternate string) {
		ev := KeyEventFromCSI(csi)
		if ev == nil {
			t.Fatalf("Failed to get parse %#v", csi)
		}
		if diff := cmp.Diff(expected, ev.Text); diff != "" {
			t.Fatalf("Failed to get text from %#v:\n%s", csi, diff)
		}
		if diff := cmp.Diff(alternate, ev.AlternateKey); diff != "" {
			t.Fatalf("Failed to get alternate from %#v:\n%s", csi, diff)
		}
	}
	test_text("121;;121u", "y", "")
	test_text("121::122;;121u", "y", "z")
}
