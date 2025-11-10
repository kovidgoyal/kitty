package images

import (
	"bytes"
	"fmt"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty"
)

var _ = fmt.Print

func TestImageSerialize(t *testing.T) {
	img, _, err := OpenImageFromReader(bytes.NewReader(kitty.KittyLogoAsPNGData))
	if err != nil {
		t.Fatal(err)
	}
	m, data := img.Serialize()
	img2, err := ImageFromSerialized(m, data)
	if err != nil {
		t.Fatal(err)
	}
	m2, data2 := img2.Serialize()
	if diff := cmp.Diff(m, m2); diff != "" {
		t.Fatalf("Image metadata failed to roundtrip:\n%s", diff)
	}
	if diff := cmp.Diff(data, data2); diff != "" {
		t.Fatalf("Image data failed to roundtrip:\n%s", diff)
	}
}
