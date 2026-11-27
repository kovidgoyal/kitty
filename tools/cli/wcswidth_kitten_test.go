// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"testing"

	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

func TestWidthTestKittenSpacingMarkWidths(t *testing.T) {
	// kitty must pass its own width test
	for _, st := range spacing_mark_tests {
		if w := wcswidth.Stringwidth(st.text); w != st.width {
			t.Fatalf("The width of %q (%s) is %d not %d", st.text, st.description, w, st.width)
		}
	}
}
