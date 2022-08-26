// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"math/big"
	"testing"
)

func TestShortUUID(t *testing.T) {
	a, err := HumanRandomId(128)
	if err != nil {
		t.Fatal(err)
	}
	b, err := HumanRandomId(128)
	if err != nil {
		t.Fatal(err)
	}
	if a == b {
		t.Fatalf("Two short uuid4's are unexpectedly equal")
	}
	if HumanUUID.pad_to_length != 22 {
		t.Fatalf("pad length for human UUID is %d not %d", HumanUUID.pad_to_length, 22)
	}
	u, err := HumanUUID.Uuid4()
	if err != nil {
		t.Fatal(err)
	}
	if len(u) != 22 {
		t.Fatalf("uuid4 %s has unexpected length: %d", u, len(u))
	}

	bi := big.NewInt(int64(1234567890123456789))
	q := num_to_string(bi, HumanUUID.alphabet, &HumanUUID.alphabet_len, HumanUUID.pad_to_length)
	const expected = "bzT6LtUjw4422222222222"
	if q != expected {
		t.Fatalf("unexpected short human serialization: %s != %s", q, expected)
	}
}
