// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

// UTF-8 decode taken from: https://bjoern.hoehrmann.de/utf-8/decoder/dfa/

type UTF8State uint32

var utf8_data []uint8 = []uint8{
	0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, // 00..1f
	0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, // 20..3f
	0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, // 40..5f
	0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, // 60..7f
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, // 80..9f
	7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, // a0..bf
	8, 8, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, // c0..df
	0xa, 0x3, 0x3, 0x3, 0x3, 0x3, 0x3, 0x3, 0x3, 0x3, 0x3, 0x3, 0x3, 0x4, 0x3, 0x3, // e0..ef
	0xb, 0x6, 0x6, 0x6, 0x5, 0x8, 0x8, 0x8, 0x8, 0x8, 0x8, 0x8, 0x8, 0x8, 0x8, 0x8, // f0..ff
	0x0, 0x1, 0x2, 0x3, 0x5, 0x8, 0x7, 0x1, 0x1, 0x1, 0x4, 0x6, 0x1, 0x1, 0x1, 0x1, // s0..s0
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 0, 1, 1, 1, 1, 1, 1, // s1..s2
	1, 2, 1, 1, 1, 1, 1, 2, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, // s3..s4
	1, 2, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 3, 1, 3, 1, 1, 1, 1, 1, 1, // s5..s6
	1, 3, 1, 1, 1, 1, 1, 3, 1, 3, 1, 1, 1, 1, 1, 1, 1, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // s7..s8
}

const (
	UTF8_ACCEPT UTF8State = 0
	UTF8_REJECT UTF8State = 1
)

func DecodeUtf8(state *UTF8State, codep *UTF8State, byte_ byte) UTF8State {
	typ := UTF8State(utf8_data[byte_])
	b := UTF8State(byte_)

	if *state != UTF8_ACCEPT {
		*codep = (b & 0x3f) | (*codep << 6)
	} else {
		*codep = (0xff >> typ) & (b)
	}

	idx := 256 + *state*16 + typ
	*state = UTF8State(utf8_data[idx])
	return *state
}

func EncodeUtf8(ch UTF8State, dest []byte) int {
	if ch < 0x80 {
		dest[0] = byte(ch)
		return 1
	}
	if ch < 0x800 {
		dest[0] = byte((ch >> 6) | 0xC0)
		dest[1] = byte((ch & 0x3F) | 0x80)
		return 2
	}
	if ch < 0x10000 {
		dest[0] = byte((ch >> 12) | 0xE0)
		dest[1] = byte(((ch >> 6) & 0x3F) | 0x80)
		dest[2] = byte((ch & 0x3F) | 0x80)
		return 3
	}
	if ch < 0x110000 {
		dest[0] = byte((ch >> 18) | 0xF0)
		dest[1] = byte(((ch >> 12) & 0x3F) | 0x80)
		dest[2] = byte(((ch >> 6) & 0x3F) | 0x80)
		dest[3] = byte((ch & 0x3F) | 0x80)
		return 4
	}
	return 0
}
