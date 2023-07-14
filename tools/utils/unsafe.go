// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"unsafe"
)

var _ = fmt.Print

// Unsafely converts s into a byte slice.
// If you modify b, then s will also be modified. This violates the
// property that strings are immutable.
func UnsafeStringToBytes(s string) (b []byte) {
	return unsafe.Slice(unsafe.StringData(s), len(s))
}

// Unsafely converts b into a string.
// If you modify b, then s will also be modified. This violates the
// property that strings are immutable.
func UnsafeBytesToString(b []byte) (s string) {
	return unsafe.String(unsafe.SliceData(b), len(b))
}
