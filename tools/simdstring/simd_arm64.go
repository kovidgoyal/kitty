// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

//go:build goexperiment.simd

package simdstring

import (
	"math/bits"
	"simd"
	"simd/archsimd"
)

// Implementations using the arm64 specific simd/archsimd package. These are
// faster than the vector size agnostic code in simd.go because the portable
// API has no way to turn a mask into a bitmask, so it has to be stored to
// memory and scanned, on every loop iteration. Here, NEON instructions are
// used to turn the mask into a 64 bit integer with four bits per byte, the
// equivalent of the commonly used SHRN trick.

// SIMD implementations available at runtime, fastest first
func simd_impls() []*impl_set {
	if simd_vector_size() == 0 {
		// emulated, slower than scalar code
		return nil
	}
	return []*impl_set{{
		"neon",
		index_byte_neon, func(t string, b byte) int { return index_byte_neon(bytes_of_string(t), b) },
		index_byte2_neon, func(t string, a, b byte) int { return index_byte2_neon(bytes_of_string(t), a, b) },
		index_c0_neon, func(t string) int { return index_c0_neon(bytes_of_string(t)) },
		not_index_byte_neon, func(t string, b byte) int { return not_index_byte_neon(bytes_of_string(t), b) },
		not_index_byte2_neon, func(t string, a, b byte) int { return not_index_byte2_neon(bytes_of_string(t), a, b) },
	}, portable_impl()}
}

// Return a 64 bit integer with four bits set for every true lane in m.
// Each 16 bit lane of the mask is shifted right by 4 and its low byte kept,
// so that the low byte has its low nibble from the even 8 bit lane and its
// high nibble from the odd 8 bit lane. shr4 must be all -4, it is passed
// in, as ShiftAllRight() is compiled to a shift by a vector (USHL) that is
// re-created on every call, even in loops.
func nibble_mask(m archsimd.Mask8x16, shr4 archsimd.Int16x8) uint64 {
	v := m.ToInt8x16().ToBits().ReshapeToUint16s().Shift(shr4).ReshapeToUint8s()
	return v.ConcatEven(v).ReshapeToUint64s().GetElem(0)
}

// Return a nibble mask with the nibbles for the first n bytes set
func valid_nibbles(n int) uint64 { return ^uint64(0) >> (64 - 4*uint(n)) }

// Return off + index of the lowest set nibble in m or -1 if m is zero
func found_at_nibble(off int, m uint64) int {
	if m == 0 {
		return -1
	}
	return off + bits.TrailingZeros64(m)>>2
}

// All the implementations below work the same way: the first vector is
// loaded from the start of data, then vectors are loaded from aligned
// addresses and finally the last vector is loaded from the end of data. These
// loads overlap, which is harmless, as the overlapping bytes are known to not
// match. Data shorter than a vector is loaded with a zero filled partial load
// and nibbles for the zero filled bytes are discarded with valid_nibbles.

func index_byte_neon(data []byte, b byte) int {
	n := archsimd.BroadcastUint8x16(b)
	shr4 := archsimd.BroadcastInt16x8(-4)
	if len(data) < 16 {
		v, l := archsimd.LoadUint8x16Part(data)
		return found_at_nibble(0, nibble_mask(v.Equal(n), shr4)&valid_nibbles(l))
	}
	v := archsimd.LoadUint8x16(data)
	if m := nibble_mask(v.Equal(n), shr4); m != 0 {
		return bits.TrailingZeros64(m) >> 2
	}
	last := len(data) - 16
	for i := aligned_start(data, 16); i < last; i += 16 {
		v := archsimd.LoadUint8x16(data[i:])
		if m := nibble_mask(v.Equal(n), shr4); m != 0 {
			return i + bits.TrailingZeros64(m)>>2
		}
	}
	v = archsimd.LoadUint8x16(data[last:])
	return found_at_nibble(last, nibble_mask(v.Equal(n), shr4))
}

func index_byte2_neon(data []byte, a, b byte) int {
	na, nb := archsimd.BroadcastUint8x16(a), archsimd.BroadcastUint8x16(b)
	shr4 := archsimd.BroadcastInt16x8(-4)
	if len(data) < 16 {
		v, l := archsimd.LoadUint8x16Part(data)
		return found_at_nibble(0, nibble_mask(v.Equal(na).Or(v.Equal(nb)), shr4)&valid_nibbles(l))
	}
	v := archsimd.LoadUint8x16(data)
	if m := nibble_mask(v.Equal(na).Or(v.Equal(nb)), shr4); m != 0 {
		return bits.TrailingZeros64(m) >> 2
	}
	last := len(data) - 16
	for i := aligned_start(data, 16); i < last; i += 16 {
		v := archsimd.LoadUint8x16(data[i:])
		if m := nibble_mask(v.Equal(na).Or(v.Equal(nb)), shr4); m != 0 {
			return i + bits.TrailingZeros64(m)>>2
		}
	}
	v = archsimd.LoadUint8x16(data[last:])
	return found_at_nibble(last, nibble_mask(v.Equal(na).Or(v.Equal(nb)), shr4))
}

func index_c0_neon(data []byte) int {
	space, del := archsimd.BroadcastUint8x16(' '), archsimd.BroadcastUint8x16(0x7f)
	shr4 := archsimd.BroadcastInt16x8(-4)
	if len(data) < 16 {
		v, l := archsimd.LoadUint8x16Part(data)
		return found_at_nibble(0, nibble_mask(v.Less(space).Or(v.Equal(del)), shr4)&valid_nibbles(l))
	}
	v := archsimd.LoadUint8x16(data)
	if m := nibble_mask(v.Less(space).Or(v.Equal(del)), shr4); m != 0 {
		return bits.TrailingZeros64(m) >> 2
	}
	last := len(data) - 16
	for i := aligned_start(data, 16); i < last; i += 16 {
		v := archsimd.LoadUint8x16(data[i:])
		if m := nibble_mask(v.Less(space).Or(v.Equal(del)), shr4); m != 0 {
			return i + bits.TrailingZeros64(m)>>2
		}
	}
	v = archsimd.LoadUint8x16(data[last:])
	return found_at_nibble(last, nibble_mask(v.Less(space).Or(v.Equal(del)), shr4))
}

func not_index_byte_neon(data []byte, b byte) int {
	n := archsimd.BroadcastUint8x16(b)
	shr4 := archsimd.BroadcastInt16x8(-4)
	if len(data) < 16 {
		v, l := archsimd.LoadUint8x16Part(data)
		return found_at_nibble(0, ^nibble_mask(v.Equal(n), shr4)&valid_nibbles(l))
	}
	v := archsimd.LoadUint8x16(data)
	if m := ^nibble_mask(v.Equal(n), shr4); m != 0 {
		return bits.TrailingZeros64(m) >> 2
	}
	last := len(data) - 16
	for i := aligned_start(data, 16); i < last; i += 16 {
		v := archsimd.LoadUint8x16(data[i:])
		if m := ^nibble_mask(v.Equal(n), shr4); m != 0 {
			return i + bits.TrailingZeros64(m)>>2
		}
	}
	v = archsimd.LoadUint8x16(data[last:])
	return found_at_nibble(last, ^nibble_mask(v.Equal(n), shr4))
}

func not_index_byte2_neon(data []byte, a, b byte) int {
	na, nb := archsimd.BroadcastUint8x16(a), archsimd.BroadcastUint8x16(b)
	shr4 := archsimd.BroadcastInt16x8(-4)
	if len(data) < 16 {
		v, l := archsimd.LoadUint8x16Part(data)
		return found_at_nibble(0, ^nibble_mask(v.Equal(na).Or(v.Equal(nb)), shr4)&valid_nibbles(l))
	}
	v := archsimd.LoadUint8x16(data)
	if m := ^nibble_mask(v.Equal(na).Or(v.Equal(nb)), shr4); m != 0 {
		return bits.TrailingZeros64(m) >> 2
	}
	last := len(data) - 16
	for i := aligned_start(data, 16); i < last; i += 16 {
		v := archsimd.LoadUint8x16(data[i:])
		if m := ^nibble_mask(v.Equal(na).Or(v.Equal(nb)), shr4); m != 0 {
			return i + bits.TrailingZeros64(m)>>2
		}
	}
	v = archsimd.LoadUint8x16(data[last:])
	return found_at_nibble(last, ^nibble_mask(v.Equal(na).Or(v.Equal(nb)), shr4))
}

// first_true and first_false are used only by the portable implementations
// in simd.go, which on arm64 are only used for emulation.
func first_true(m simd.Mask8s) int  { return first_true_portable(m) }
func first_false(m simd.Mask8s) int { return first_false_portable(m) }
