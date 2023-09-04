package base85

import (
	"fmt"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

type pair struct {
	src, encoded string
}

func TestBase85(t *testing.T) {
	dst, dst2 := [8]byte{}, [8]byte{}
	decode := decoder_array()
	var el int
	for _, x := range []string{"M", "Ma", "Man", "Man "} {
		a := []byte(x)
		if el = encodeChunk(dst[:], a); el != EncodedLen(len(a)) {
			t.Fatalf("Encoded len for %#v wrong: %d != %d", x, el, EncodedLen(len(a)))
		}
		encoded := dst[:el]
		dl, bad_idx := decodeChunk(&decode, dst2[:], encoded)
		if bad_idx != 0 {
			t.Fatalf("Decode for %#v returned bad data at: %d (%#v)", x, bad_idx, encoded)
		}
		if dl != DecodedLen(len(encoded)) {
			t.Fatalf("Decoded len for %#v wrong: %d != %d", x, dl, DecodedLen(len(a)))
		}
		decoded := string(dst2[:dl])
		if diff := cmp.Diff(x, decoded); diff != "" {
			t.Fatalf("Roundtrip failed for %#v: %s", x, diff)
		}
	}
	for _, p := range []pair{
		{"M", "O#"},
		{"Manual", "O<`_zVQc"},
	} {
		q := EncodeToString([]byte(p.src))
		if diff := cmp.Diff(p.encoded, q); diff != "" {
			t.Fatalf("Incorrect encoding of: %#v\n%s", p.src, diff)
		}
		sc, err := DecodeString(q)
		if err != nil {
			t.Fatalf("Failed to decode %#v with error: %s", p.src, err)
		}
		if diff := cmp.Diff(p.src, string(sc)); diff != "" {
			t.Fatalf("Failed to roundtrip %#v\n%s", p.src, diff)
		}
	}
}
