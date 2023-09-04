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
		dl, bad_idx := decodeChunk(decode, dst2[:], encoded)
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
		{
			"Man is distinguished, not only by his reason, but by this singular passion from " +
				"other animals, which is a lust of the mind, that by a perseverance of delight in " +
				"the continued and indefatigable generation of knowledge, exceeds the short " +
				"vehemence of any carnal pleasure.",
			"O<`^zX>%ZCX>)XGZfA9Ab7*B`EFf-gbRchTY<VDJc_3(Mb0BhMVRLV8EFfZabRc4RAarPHb0BkRZfA9DVR9gFVRLh7Z*CxFa&K)QZ**v7av))DX>DO_b1WctXlY|;AZc?TVIXXEb95kYW*~HEWgu;7Ze%PVbZB98AYyqSVIXj2a&u*NWpZI|V`U(3W*}r`Y-wj`bRcPNAarPDAY*TCbZKsNWn>^>Ze$>7Ze(R<VRUI{VPb4$AZKN6WpZJ3X>V>IZ)PBCZf|#NWn^b%EFfigV`XJzb0BnRWgv5CZ*p`Xc4cT~ZDnp_Wgu^6AYpEKAY);2ZeeU7aBO8^b9HiME&",
		},
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
