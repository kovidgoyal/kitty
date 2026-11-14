package icat

import (
	"fmt"
	"image"
	"testing"
)

var _ = fmt.Print

func TestScaling(t *testing.T) {
	for _, tc := range []struct {
		w, h, pw, ph, ew, eh int
	}{
		{1000, 50, 800, 600, 800, 40},
		{1000, 50, 800000, 600, 12000, 600},
		{100, 50, 800, 600, 800, 400},
		{1920, 1080, 800, 600, 800, 450},
		{300, 900, 800, 600, 200, 600},
		{400, 300, 800, 600, 800, 600},
	} {
		aw, ah := scale_up(tc.w, tc.h, tc.pw, tc.ph)
		actual := image.Pt(aw, ah)
		expected := image.Pt(tc.ew, tc.eh)
		if actual != expected {
			t.Fatalf("want: %v got: %v", expected, actual)
		}
	}
}
