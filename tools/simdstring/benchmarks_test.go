// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package simdstring

import (
	"bytes"
	"fmt"
	"testing"
)

var _ = fmt.Print

func haystack(filler, needle byte, pos int) []byte {
	var data []byte
	if pos > 0 {
		data = append(bytes.Repeat([]byte{filler}, pos-1), needle)
	} else {
		data = []byte{needle}
	}
	return data
}

var sizes = []int{6, 327, 9875, 1198673}

func BenchmarkIndexByte(b *testing.B) {
	t := func(pos int, which string) {
		data := haystack('a', 'q', pos)
		f := IndexByte
		switch which {
		case "scalar":
			f = index_byte_scalar
		case "stdlib":
			f = bytes.IndexByte
		}
		b.Run(fmt.Sprintf("%s_sz=%d", which, pos), func(b *testing.B) {
			for i := 0; i < b.N; i++ {
				f(data, 'q')
			}
		})
	}
	for _, pos := range sizes {
		t(pos, "simdstring")
		t(pos, "scalar")
		t(pos, "stdlib")
	}
}

func BenchmarkIndexByte2(b *testing.B) {
	t := func(pos int, which string) {
		data := haystack('a', 'q', pos)
		f := IndexByte2
		switch which {
		case "scalar":
			f = index_byte2_scalar
		}
		b.Run(fmt.Sprintf("%s_sz=%d", which, pos), func(b *testing.B) {
			for i := 0; i < b.N; i++ {
				f(data, 'q', 'x')
			}
		})
	}
	for _, pos := range sizes {
		t(pos, "simdstring")
		t(pos, "scalar")
	}
}
