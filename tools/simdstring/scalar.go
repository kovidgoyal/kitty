// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package simdstring

func index_byte_scalar(data []byte, b byte) int {
	for i, ch := range data {
		if ch == b {
			return i
		}
	}
	return -1
}

func index_byte_string_scalar(data string, b byte) int {
	for i := 0; i < len(data); i++ {
		if data[i] == b {
			return i
		}
	}
	return -1
}

func index_byte2_scalar(data []byte, a, b byte) int {
	for i, ch := range data {
		switch ch {
		case a, b:
			return i
		}
	}
	return -1
}

func index_byte2_string_scalar(data string, a, b byte) int {
	for i := 0; i < len(data); i++ {
		switch data[i] {
		case a, b:
			return i
		}
	}
	return -1
}

func index_c0_scalar(data []byte) int {
	for i := 0; i < len(data); i++ {
		if data[i] == 0x7f || data[i] < ' ' {
			return i
		}
	}
	return -1
}

func index_c0_string_scalar(data string) int {
	for i := 0; i < len(data); i++ {
		if data[i] == 0x7f || data[i] < ' ' {
			return i
		}
	}
	return -1
}
