// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package simdstring

import (
	"runtime"

	"golang.org/x/sys/cpu"
)

var Have128bit = false
var Have256bit = false
var VectorSize = 1

// Return the index at which b first occurs in data. If not found -1 is returned.
var IndexByte func(data []byte, b byte) int = index_byte_scalar

// Return the index at which either a or b first occurs in text. If neither is
// found -1 is returned.
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

func init() {
	switch runtime.GOARCH {
	case "amd64":
		if cpu.Initialized {
			Have128bit = cpu.X86.HasSSE42 && HasSIMD128Code
			Have256bit = cpu.X86.HasAVX2 && HasSIMD256Code
		}
	case "arm64":
		Have128bit = HasSIMD128Code
		Have256bit = HasSIMD256Code
	}
	if Have256bit {
		IndexByte = index_byte_asm_256
		IndexByteString = index_byte_string_asm_256
		IndexByte2 = index_byte2_asm_256
		IndexByte2String = index_byte2_string_asm_256
		IndexC0 = index_c0_asm_256
		IndexC0String = index_c0_string_asm_256
		VectorSize = 32
	} else if Have128bit {
		IndexByte = index_byte_asm_128
		IndexByteString = index_byte_string_asm_128
		IndexByte2 = index_byte2_asm_128
		IndexByte2String = index_byte2_string_asm_128
		IndexC0 = index_c0_asm_128
		IndexC0String = index_c0_string_asm_128
		VectorSize = 16
	}
}
