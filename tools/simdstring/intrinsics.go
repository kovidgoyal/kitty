// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package simdstring

import (
	"runtime"
	"unsafe"

	"golang.org/x/sys/cpu"
)

var Have128bit = false
var Have256bit = false
var VectorSize = 1

// Return the index at which either a or b first occurs in data. If neither is
// found -1 is returned. Can read upto VectorSize-1 bytes beyond the end of data.
var UnsafeIndexByte2 func(data []byte, a, b byte) int = index_byte2_scalar

// Return the index at which either a or b first occurs in text. If neither is
// found -1 is returned. Can read upto VectorSize-1 bytes beyond the end of text.
var UnsafeIndexByte2String func(text string, a, b byte) int = index_byte2_string_scalar

func get_safe_slice(addr uintptr, mask, datalen int) (align_len, vecsafe_len int) {
	vecsize := mask + 1
	if datalen < vecsize {
		return datalen, 0
	}
	align_len = vecsize - int(addr&uintptr(mask))
	datalen -= align_len
	vecsafe_len = datalen - datalen&mask
	return
}

func get_safe_slice_with_cap(addr uintptr, mask, datalen, datacap int) (align_len, vecsafe_len int) {
	if datacap > datalen+mask {
		return 0, datalen
	}
	return get_safe_slice(addr, mask, datalen)
}

// Return the index at which either a or b first occurs in data. If neither is
// found -1 is returned.
func IndexByte2(data []byte, a, b byte) int {
	align_len, vecsafe_len := get_safe_slice_with_cap(uintptr(unsafe.Pointer(&data)), VectorSize-1, len(data), cap(data))
	if align_len > 0 {
		if ans := index_byte2_scalar(data[:align_len], a, b); ans > -1 {
			return ans
		}
		data = data[align_len:]
	}
	if vecsafe_len > 0 {
		if ans := UnsafeIndexByte2(data[:vecsafe_len], a, b); ans > -1 {
			return align_len + ans
		}
		data = data[vecsafe_len:]
	}
	if len(data) > 0 {
		if ans := index_byte2_scalar(data, a, b); ans > -1 {
			return ans + align_len + vecsafe_len
		}
	}
	return -1
}

// Return the index at which either a or b first occurs in data. If neither is
// found -1 is returned.
func IndexByte2String(data string, a, b byte) int {
	align_len, vecsafe_len := get_safe_slice(uintptr(unsafe.Pointer(&data)), VectorSize-1, len(data))
	if align_len > 0 {
		if ans := index_byte2_string_scalar(data[:align_len], a, b); ans > -1 {
			return ans
		}
		data = data[align_len:]
	}
	if vecsafe_len > 0 {
		if ans := UnsafeIndexByte2String(data[:vecsafe_len], a, b); ans > -1 {
			return align_len + ans
		}
		data = data[vecsafe_len:]
	}
	if len(data) > 0 {
		if ans := index_byte2_string_scalar(data, a, b); ans > -1 {
			return ans + align_len + vecsafe_len
		}
	}
	return -1
}

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
		UnsafeIndexByte2 = index_byte2_asm_256
		UnsafeIndexByte2String = index_byte2_string_asm_256
		VectorSize = 32
	} else if Have128bit {
		UnsafeIndexByte2 = index_byte2_asm_128
		UnsafeIndexByte2String = index_byte2_string_asm_128
		VectorSize = 16
	}
}
