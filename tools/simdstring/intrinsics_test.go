// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package simdstring

import (
	"bytes"
	"fmt"
	"runtime"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func test_load(src []byte) []byte {
	ans := make([]byte, len(src))
	if len(src) == 16 {
		test_load_asm_128(src, ans)
	} else {
		test_load_asm_256(src, ans)
	}
	return ans
}

func test_set1_epi8(b byte, sz int) []byte {
	ans := make([]byte, sz)
	if sz == 16 {
		test_set1_epi8_asm_128(b, ans)
	} else {
		test_set1_epi8_asm_256(b, ans)
	}
	return ans
}

func test_cmpeq_epi8(a, b []byte) []byte {
	ans := make([]byte, len(a))
	if len(ans) == 16 {
		test_cmpeq_epi8_asm_128(a, b, ans)
	} else {
		test_cmpeq_epi8_asm_256(a, b, ans)
	}
	return ans
}

func test_cmplt_epi8(a, b []byte) []byte {
	ans := make([]byte, len(a))
	if len(ans) == 16 {
		test_cmplt_epi8_asm_128(a, b, ans)
	} else {
		test_cmplt_epi8_asm_256(a, b, ans)
	}
	return ans
}

func test_or(a, b []byte) []byte {
	ans := make([]byte, len(a))
	if len(ans) == 16 {
		test_or_asm_128(a, b, ans)
	} else {
		test_or_asm_256(a, b, ans)
	}
	return ans
}

func test_jump_if_zero(a []byte) int {
	if len(a) == 16 {
		return test_jump_if_zero_asm_128(a)
	}
	return test_jump_if_zero_asm_256(a)
}

func test_count_to_match(a []byte, b byte) int {
	if len(a) == 16 {
		return test_count_to_match_asm_128(a, b)
	}
	return test_count_to_match_asm_256(a, b)
}

func ordered_bytes(size int) []byte {
	ans := make([]byte, size)
	for i := range ans {
		ans[i] = byte(i)
	}
	return ans
}

func broadcast_byte(b byte, size int) []byte {
	return bytes.Repeat([]byte{b}, size)
}

func TestSIMDStringOps(t *testing.T) {
	sizes := []int{}
	if Have128bit {
		sizes = append(sizes, 16)
	}
	if Have256bit {
		sizes = append(sizes, 32)
	}

	if len(sizes) == 0 {
		t.Skip("skipping as no SIMD available at runtime")
	}
	test := func(haystack []byte, a, b byte) {
		var actual int
		safe_haystack := append(bytes.Repeat([]byte{'<'}, 64), haystack...)
		safe_haystack = append(safe_haystack, bytes.Repeat([]byte{'>'}, 64)...)
		haystack = safe_haystack[64 : 64+len(haystack)]
		expected := index_byte2_scalar(haystack, a, b)

		for _, sz := range sizes {
			switch sz {
			case 16:
				actual = index_byte2_asm_128(haystack, a, b)
			case 32:
				actual = index_byte2_asm_256(haystack, a, b)
			}
			if actual != expected {
				t.Fatalf("Failed to find '%c' or '%c' in: %#v (%d != %d) at size: %d", a, b, string(haystack), expected, actual, sz)
			}
		}

	}
	tests := func(h string, a, b byte) {
		test([]byte(h), a, b)
		for _, sz := range []int{16, 32, 64, 79} {
			q := strings.Repeat(" ", sz) + h
			test([]byte(q), a, b)
		}
	}
	test(nil, '1', '2')
	test([]byte{}, '1', '2')

	tests("", '<', '>')
	tests("a", 0, 0)
	tests("a", '<', '>')
	tests("dsdfsfa", '1', 'a')
	tests("xa", 'a', 'a')
	tests("bbb", 'a', '1')
	tests("bba", 'a', '<')
	tests("baa", '>', 'a')

	tbs := func(addr, datalen int) {
		align_len, vecsafelen := get_safe_slice(uintptr(addr), 15, datalen)
		if vecsafelen < 0 || align_len+vecsafelen > datalen || datalen-vecsafelen-align_len > 15 || align_len < 0 {
			t.Fatalf("Invalid bounds for addr=%d datalen=%d (align_len=%d vecsafelen=%d)", addr, datalen, align_len, vecsafelen)
		}
		if vecsafelen > 0 {
			pos := addr + align_len
			if pos&15 != 0 {
				t.Fatalf("Non-aligned vector read for addr=%d datalen=%d (align_len=%d vecsafelen=%d)", addr, datalen, align_len, vecsafelen)
			}
			limit := pos + vecsafelen
			read := func() {
				if pos+16 > addr+datalen {
					t.Fatalf("Read past limit for addr=%d datalen=%d (align_len=%d vecsafelen=%d pos=%d)", addr, datalen, align_len, vecsafelen, pos)
				}
			}
			read()
			for ; pos < limit; pos += 16 {
				read()
			}
		}
	}

	for datalen := 0; datalen < 33; datalen++ {
		for addr := 0; addr < 32; addr++ {
			tbs(addr, datalen)
		}
	}
}

func TestIntrinsics(t *testing.T) {
	switch runtime.GOARCH {
	case "amd64":
		if !HasSIMD128Code {
			t.Fatal("SIMD 128bit code not built")
		}
		if !HasSIMD256Code {
			t.Fatal("SIMD 256bit code not built")
		}
	case "arm64":
		if !HasSIMD128Code {
			t.Fatal("SIMD 128bit code not built")
		}
		if !Have128bit {
			t.Fatal("SIMD 128bit support not available at runtime")
		}
	}
	ae := func(sz int, func_name string, a, b any) {
		if s := cmp.Diff(a, b); s != "" {
			t.Fatalf("%s failed with size: %d\n%s", func_name, sz, s)
		}
	}
	tests := []func(int){}

	tests = append(tests, func(sz int) {
		a := ordered_bytes(sz)
		ae(sz, `load_test`, a, test_load(a))
	})
	tests = append(tests, func(sz int) {
		for _, b := range []byte{1, 0b110111, 0xff, 0} {
			ae(sz, `set1_epi8_test`, broadcast_byte(b, sz), test_set1_epi8(b, sz))
		}
	})
	tests = append(tests, func(sz int) {
		a := ordered_bytes(sz)
		b := ordered_bytes(sz)
		ans := test_cmpeq_epi8(a, b)
		ae(sz, `cmpeq_epi8_test`, broadcast_byte(0xff, sz), ans)
		threshold := -1
		a[1] = byte(threshold)
		a[2] = byte(threshold - 1)
		ans = test_cmplt_epi8(a, broadcast_byte(byte(threshold), sz))
		expected := broadcast_byte(0xff, sz)
		expected[1] = 0
		expected[2] = 0
		ae(sz, `cmplt_epi8_test`, expected, ans)
	})
	tests = append(tests, func(sz int) {
		a := make([]byte, sz)
		b := make([]byte, sz)
		c := make([]byte, sz)
		a[0] = 0xff
		b[0] = 0xff
		b[1] = 0xff
		a[sz-1] = 1
		b[sz-1] = 2
		for i := range c {
			c[i] = a[i] | b[i]
		}
		ans := test_or(a, b)
		ae(sz, `or_test`, c, ans)
	})

	tests = append(tests, func(sz int) {
		a := make([]byte, sz)
		if e := test_jump_if_zero(a); e != 0 {
			t.Fatalf("Did not detect zero register")
		}
		for i := 0; i < sz; i++ {
			a = make([]byte, sz)
			a[i] = 1
			if e := test_jump_if_zero(a); e != 1 {
				t.Fatalf("Did not detect non-zero register")
			}
		}
	})

	tests = append(tests, func(sz int) {
		a := ordered_bytes(sz)
		if e := test_count_to_match(a, 77); e != -1 {
			t.Fatalf("Unexpectedly found byte at: %d", e)
		}
		for i := 0; i < sz; i++ {
			if e := test_count_to_match(a, byte(i)); e != i {
				t.Fatalf("Failed to find the byte: %d (%d != %d)", i, i, e)
			}
		}
		a[7] = 0x34
		if e := test_count_to_match(a, 0x34); e != 7 {
			t.Fatalf("Failed to find the byte: %d (%d != %d)", 0x34, 7, e)
		}
	})

	sizes := []int{}

	if Have128bit {
		sizes = append(sizes, 16)
	}
	if Have256bit {
		sizes = append(sizes, 32)
	}
	if len(sizes) == 0 {
		t.Skip("skipping as no SIMD available at runtime")
	}
	for _, sz := range sizes {
		for _, test := range tests {
			test(sz)
		}
	}

}
