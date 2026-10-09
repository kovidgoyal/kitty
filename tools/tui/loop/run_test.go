package loop

import (
	"testing"
)

func TestZeroScreenSize(t *testing.T) {
	lp := Loop{}
	if err := lp.handle_csi([]byte("48;0;0;0;0t")); err != nil {
		t.Fatal(err)
	}
	if err := lp.handle_csi([]byte("48;24;0;480;0t")); err != nil {
		t.Fatal(err)
	}
	s := lp.screen_size
	if s.WidthCells != 0 || s.CellWidth != 0 || s.HeightCells != 24 || s.CellHeight != 20 {
		t.Fatalf("unexpected screen size: %#v", s)
	}
}
