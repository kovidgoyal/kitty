// License: GPLv3 Copyright: 2025, Kovid Goyal, <kovid at kovidgoyal.net>

package style

import (
	"testing"
)

func TestParseColor(t *testing.T) {
	type tr struct {
		input    string
		expected RGBA
	}
	c := func(t string, r, g, b uint8) tr { return tr{t, RGBA{r, g, b, 0}} }
	tests := []tr{
		c(`#eee # comment`, 0xee, 0xee, 0xee),
		c(`#234567`, 0x23, 0x45, 0x67),
		c(`#abcabcdef`, 0xab, 0xab, 0xde),
		c(`rgb:e/e/e # comment`, 0xee, 0xee, 0xee),
		c(`rgb:23/45/67`, 0x23, 0x45, 0x67),
		c(`rgb:abc/abc/def`, 0xab, 0xab, 0xde),
		c(`red`, 0xff, 0, 0),
		c(`alice blue # comment`, 240, 248, 255),
		c(`oklch(1,0,0)`, 255, 255, 255),
		c(`oklch(0,0,0)`, 0, 0, 0),
		c(`oklch(0.5,0.1,180)`, 0, 117, 101),
		c(`oklch(0.7 0.15 140) # comment`, 0x68, 0xb4, 0x57),
		c(`oklch(0.9 0.05 265)`, 0xce, 0xde, 0xff),
		c(`lab(70 50 -30)`, 0xea, 0x88, 0xe2),
		c(`lab(50,0,0)`, 199, 199, 199),
		c(`lab(100,0,0)`, 255, 255, 255),
		c(`lab(0,0,0)`, 0, 0, 0),
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			actual, err := ParseColor(tt.input)
			if actual != tt.expected {
				t.Errorf("ParseColor(%#v) error = %v, got %v wanted %v", tt.input, err, actual, tt.expected)
			}
		})
	}
}
