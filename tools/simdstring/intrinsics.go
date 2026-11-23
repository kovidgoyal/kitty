// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package simdstring

// Whether hardware accelerated SIMD implementations are in use, and the
// size of the vectors they use, in bytes. When the program is built without
// GOEXPERIMENT=simd or the CPU has no usable SIMD instructions, the scalar
// implementations are used and VectorSize is 1.
var Have128bit = false
var Have256bit = false
var VectorSize = 1

// Return the index at which b first occurs in data. If not found -1 is returned.
var IndexByte func(data []byte, b byte) int = index_byte_scalar

// Return the index at which b first occurs in text. If not found -1 is returned.
var IndexByteString func(text string, b byte) int = index_byte_string_scalar

// Return the index at which either a or b first occurs in data. If neither is
// found -1 is returned.
var IndexByte2 func(data []byte, a, b byte) int = index_byte2_scalar

// Return the index at which either a or b first occurs in text. If neither is
// found -1 is returned.
var IndexByte2String func(text string, a, b byte) int = index_byte2_string_scalar

// Return the index at which the first C0 byte is found or -1 when no such bytes are present.
var IndexC0 func(data []byte) int = index_c0_scalar

// Return the index at which the first C0 byte is found or -1 when no such bytes are present.
var IndexC0String func(data string) int = index_c0_string_scalar

// Return the index of the first byte in data that is not equal to b. If all bytes equal b, -1 is returned.
var NotIndexByte func(data []byte, b byte) int = not_index_byte_scalar

// Return the index of the first byte in text that is not equal to b. If all bytes equal b, -1 is returned.
var NotIndexByteString func(text string, b byte) int = not_index_byte_string_scalar

// Return the index of the first byte in data that is neither a nor b. If all bytes are a or b, -1 is returned.
var NotIndexByte2 func(data []byte, a, b byte) int = not_index_byte2_scalar

// Return the index of the first byte in text that is neither a nor b. If all bytes are a or b, -1 is returned.
var NotIndexByte2String func(text string, a, b byte) int = not_index_byte2_string_scalar

// A set of implementations of all the functions in this package
type impl_set struct {
	name                   string
	index_byte             func(data []byte, b byte) int
	index_byte_string      func(text string, b byte) int
	index_byte2            func(data []byte, a, b byte) int
	index_byte2_string     func(text string, a, b byte) int
	index_c0               func(data []byte) int
	index_c0_string        func(text string) int
	not_index_byte         func(data []byte, b byte) int
	not_index_byte_string  func(text string, b byte) int
	not_index_byte2        func(data []byte, a, b byte) int
	not_index_byte2_string func(text string, a, b byte) int
}

func scalar_impl() *impl_set {
	return &impl_set{
		"scalar",
		index_byte_scalar, index_byte_string_scalar, index_byte2_scalar, index_byte2_string_scalar,
		index_c0_scalar, index_c0_string_scalar, not_index_byte_scalar, not_index_byte_string_scalar,
		not_index_byte2_scalar, not_index_byte2_string_scalar,
	}
}

func init() {
	VectorSize = max(1, simd_vector_size())
	Have128bit = VectorSize >= 16
	Have256bit = VectorSize >= 32
	if impls := simd_impls(); len(impls) > 0 {
		// the first implementation is the fastest
		i := impls[0]
		IndexByte, IndexByteString = i.index_byte, i.index_byte_string
		IndexByte2, IndexByte2String = i.index_byte2, i.index_byte2_string
		IndexC0, IndexC0String = i.index_c0, i.index_c0_string
		NotIndexByte, NotIndexByteString = i.not_index_byte, i.not_index_byte_string
		NotIndexByte2, NotIndexByte2String = i.not_index_byte2, i.not_index_byte2_string
	}
}
