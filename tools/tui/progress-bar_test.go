// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
	"testing"
)

var _ = fmt.Print

func TestRenderProgressBar(t *testing.T) {

	test := func(frac float64, width int) {
		b := RenderProgressBar(frac, width)
		a := wcswidth.Stringwidth(b)
		if a != width {
			t.Fatalf("Actual length %d != Expected length %d with fraction: %v\n%s", a, width, frac, b)
		}
	}
	test(0.9376609994848016, 47)
	test(0.9459041731066461, 47)
	test(0.9500257599175682, 47)
}
