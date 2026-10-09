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

func TestMalformedResizeReport(t *testing.T) {
	lp := Loop{}
	for _, csi := range []string{"t", "1t", "48t", "48;t", "8;24;80;0;0t", "48;-1;80;0;0t", "48;a;b;c;dt"} {
		if err := lp.handle_csi([]byte(csi)); err != nil {
			t.Fatalf("unexpected error for %#v: %s", csi, err)
		}
		if lp.seen_inband_resize {
			t.Fatalf("malformed resize report %#v was accepted", csi)
		}
	}
	if err := lp.handle_csi([]byte("48;24;80;480;800;1t")); err != nil {
		t.Fatal(err)
	}
	s := lp.screen_size
	if s.HeightCells != 24 || s.WidthCells != 80 || s.HeightPx != 480 || s.WidthPx != 800 {
		t.Fatalf("unexpected screen size: %#v", s)
	}
}
