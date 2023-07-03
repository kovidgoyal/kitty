// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package random

import (
	"crypto/rand"
	"fmt"
	"math/big"

	"golang.org/x/exp/constraints"
)

var _ = fmt.Print

// Return a random integer in the range [0, limit). limit must be > 0
func Int[T constraints.Integer](limit T) T {
	b := big.NewInt(int64(limit))
	n, err := rand.Int(rand.Reader, b)
	if err != nil {
		panic(err)
	}
	return T(n.Uint64())
}

// Return one of items randomnly
func Choice[T any](items ...T) T {
	return items[Int(len(items))]
}

// Write randomn bytes into the provided slice
func Bytes(b []byte) {
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
}
