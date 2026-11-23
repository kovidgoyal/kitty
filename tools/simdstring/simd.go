// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

//go:build goexperiment.simd

package simdstring

import (
	"simd"
	"unsafe"
)

// The implementations in this file use the vector size agnostic simd
// package. The compiler generates a specialized copy of every function in
// this file for each vector size supported by the target architecture and
// the exported entry points dispatch to the right copy at runtime.
//
// Every function follows the same pattern: full vectors are loaded from
// the start of the data, then the last full vector is loaded from the end
// of the data, overlapping already examined bytes, which is harmless as
// those are known not to match. Data shorter than a vector is zero filled
// to a full vector, so matches at indices >= len(data) are discarded.

const HasSIMDCode = true

func simd_vector_size() int {
	if simd.Emulated() {
		return 0
	}
	return simd.VectorBitSize() / 8
}

// The implementations in this file. They work on all architectures, being
// emulated in the absence of hardware support. On amd64 and arm64 the faster
// archsimd based implementations are used instead, these are used on other
// architectures with hardware SIMD support and for testing.
func portable_impl() *impl_set {
	return &impl_set{
		"portable",
		index_byte_simd, index_byte_string_simd, index_byte2_simd, index_byte2_string_simd,
		index_c0_simd, index_c0_string_simd, not_index_byte_simd, not_index_byte_string_simd,
		not_index_byte2_simd, not_index_byte2_string_simd,
	}
}

func bytes_of_string(s string) []byte {
	return unsafe.Slice(unsafe.StringData(s), len(s))
}

// Return the offset from the start of data of the first address after it
// that is aligned to vl, which must be a power of two
func aligned_start(data []byte, vl int) int {
	return vl - int(uintptr(unsafe.Pointer(unsafe.SliceData(data)))&uintptr(vl-1))
}

// Load data shorter than a vector, zero filling the rest of the vector.
// simd.LoadUint8sPart() is not used as, as of Go 1.27, with 512 bit vectors
// it reads a full vector from memory and so can fault when data is just
// before an unmapped page.
func load_short(data []byte) simd.Uint8s {
	var buf [64]byte // large enough for the largest vectors (512 bits)
	copy(buf[:], data)
	return simd.LoadUint8s(buf[:])
}

// Return the index of the first byte in data equal to b or -1
func index_byte_simd(data []byte, b byte) int {
	needle := simd.BroadcastUint8s(b)
	vl := needle.Len()
	if len(data) < vl {
		if len(data) == 0 {
			return -1
		}
		v, n := load_short(data), len(data)
		if idx := first_true(v.Equal(needle)); idx < n {
			return idx
		}
		return -1
	}
	last := len(data) - vl
	for i := 0; i < last; i += vl {
		if idx := first_true(simd.LoadUint8s(data[i:]).Equal(needle)); idx > -1 {
			return i + idx
		}
	}
	if idx := first_true(simd.LoadUint8s(data[last:]).Equal(needle)); idx > -1 {
		return last + idx
	}
	return -1
}

func index_byte_string_simd(text string, b byte) int {
	return index_byte_simd(bytes_of_string(text), b)
}

// Return the index of the first byte in data equal to either a or b or -1
func index_byte2_simd(data []byte, a, b byte) int {
	na, nb := simd.BroadcastUint8s(a), simd.BroadcastUint8s(b)
	vl := na.Len()
	if len(data) < vl {
		if len(data) == 0 {
			return -1
		}
		v, n := load_short(data), len(data)
		if idx := first_true(v.Equal(na).Or(v.Equal(nb))); idx < n {
			return idx
		}
		return -1
	}
	last := len(data) - vl
	for i := 0; i < last; i += vl {
		v := simd.LoadUint8s(data[i:])
		if idx := first_true(v.Equal(na).Or(v.Equal(nb))); idx > -1 {
			return i + idx
		}
	}
	v := simd.LoadUint8s(data[last:])
	if idx := first_true(v.Equal(na).Or(v.Equal(nb))); idx > -1 {
		return last + idx
	}
	return -1
}

func index_byte2_string_simd(text string, a, b byte) int {
	return index_byte2_simd(bytes_of_string(text), a, b)
}

// Return the index of the first C0 control code (bytes < 0x20 and 0x7f) in data or -1
func index_c0_simd(data []byte) int {
	// There is no unsigned less than comparison in the portable API, so use
	// min(x, 0x1f) == x <=> x <= 0x1f
	below_space, del := simd.BroadcastUint8s(' '-1), simd.BroadcastUint8s(0x7f)
	vl := del.Len()
	if len(data) < vl {
		if len(data) == 0 {
			return -1
		}
		v, n := load_short(data), len(data)
		if idx := first_true(v.Min(below_space).Equal(v).Or(v.Equal(del))); idx < n {
			return idx
		}
		return -1
	}
	last := len(data) - vl
	for i := 0; i < last; i += vl {
		v := simd.LoadUint8s(data[i:])
		if idx := first_true(v.Min(below_space).Equal(v).Or(v.Equal(del))); idx > -1 {
			return i + idx
		}
	}
	v := simd.LoadUint8s(data[last:])
	if idx := first_true(v.Min(below_space).Equal(v).Or(v.Equal(del))); idx > -1 {
		return last + idx
	}
	return -1
}

func index_c0_string_simd(text string) int {
	return index_c0_simd(bytes_of_string(text))
}

// Return the index of the first byte in data not equal to b or -1
func not_index_byte_simd(data []byte, b byte) int {
	needle := simd.BroadcastUint8s(b)
	vl := needle.Len()
	if len(data) < vl {
		if len(data) == 0 {
			return -1
		}
		v, n := load_short(data), len(data)
		if idx := first_false(v.Equal(needle)); idx < n {
			return idx
		}
		return -1
	}
	last := len(data) - vl
	for i := 0; i < last; i += vl {
		if idx := first_false(simd.LoadUint8s(data[i:]).Equal(needle)); idx > -1 {
			return i + idx
		}
	}
	if idx := first_false(simd.LoadUint8s(data[last:]).Equal(needle)); idx > -1 {
		return last + idx
	}
	return -1
}

func not_index_byte_string_simd(text string, b byte) int {
	return not_index_byte_simd(bytes_of_string(text), b)
}

// Return the index of the first byte in data equal to neither a nor b or -1
func not_index_byte2_simd(data []byte, a, b byte) int {
	na, nb := simd.BroadcastUint8s(a), simd.BroadcastUint8s(b)
	vl := na.Len()
	if len(data) < vl {
		if len(data) == 0 {
			return -1
		}
		v, n := load_short(data), len(data)
		if idx := first_false(v.Equal(na).Or(v.Equal(nb))); idx < n {
			return idx
		}
		return -1
	}
	last := len(data) - vl
	for i := 0; i < last; i += vl {
		v := simd.LoadUint8s(data[i:])
		if idx := first_false(v.Equal(na).Or(v.Equal(nb))); idx > -1 {
			return i + idx
		}
	}
	v := simd.LoadUint8s(data[last:])
	if idx := first_false(v.Equal(na).Or(v.Equal(nb))); idx > -1 {
		return last + idx
	}
	return -1
}

func not_index_byte2_string_simd(text string, a, b byte) int {
	return not_index_byte2_simd(bytes_of_string(text), a, b)
}
