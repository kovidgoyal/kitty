// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

//go:build goexperiment.simd

package simdstring

import (
	"encoding/binary"
	"math/bits"
	"simd"
)

// The portable simd API has no way to convert a mask to a bitmask or to
// find the first set lane, so store the mask as bytes (0xff for true lanes)
// and scan it a word at a time.
func first_set_byte_portable(v simd.Uint8s) int {
	var buf [64]byte // large enough for the largest vectors (512 bits)
	v.Store(buf[:])
	n := v.Len()
	for i := 0; i < n; i += 8 {
		if w := binary.LittleEndian.Uint64(buf[i:]); w != 0 {
			return i + bits.TrailingZeros64(w)/8
		}
	}
	return -1
}

// Return the index of the first true lane in m or -1
func first_true_portable(m simd.Mask8s) int {
	return first_set_byte_portable(m.ToInt8s().ToBits())
}

// Return the index of the first false lane in m or -1
func first_false_portable(m simd.Mask8s) int {
	return first_set_byte_portable(m.ToInt8s().ToBits().Not())
}
