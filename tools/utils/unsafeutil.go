// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"unsafe"
)

// stringHeader is the runtime representation of a string.
// It should be identical to reflect.StringHeader
type stringHeader struct {
	data      unsafe.Pointer
	stringLen int
}

// sliceHeader is the runtime representation of a slice.
// It should be identical to reflect.sliceHeader
type sliceHeader struct {
	data     unsafe.Pointer
	sliceLen int
	sliceCap int
}

// Unsafely converts s into a byte slice.
// If you modify b, then s will also be modified. This violates the
// property that strings are immutable.
func UnsafeStringToBytes(s string) (b []byte) {
	stringHeader := (*stringHeader)(unsafe.Pointer(&s))
	sliceHeader := (*sliceHeader)(unsafe.Pointer(&b))
	sliceHeader.data = stringHeader.data
	sliceHeader.sliceLen = len(s)
	sliceHeader.sliceCap = len(s)
	return b
}

// Unsafely converts b into a string.
// If you modify b, then s will also be modified. This violates the
// property that strings are immutable.
func UnsafeBytesToString(b []byte) (s string) {
	sliceHeader := (*sliceHeader)(unsafe.Pointer(&b))
	stringHeader := (*stringHeader)(unsafe.Pointer(&s))
	stringHeader.data = sliceHeader.data
	stringHeader.stringLen = len(b)
	return s
}
