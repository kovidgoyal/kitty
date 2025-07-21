// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package simdstring

import (
	"bytes"
	"fmt"
	"runtime"
	"strings"
	"testing"
	"unsafe"

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

func test_cmplt_epi8(t *testing.T, a, b []byte) []byte {
	ans := make([]byte, len(a))
	var prev []byte
	for which := 0; which < 3; which++ {
		if len(ans) == 16 {
			test_cmplt_epi8_asm_128(a, b, which, ans)
		} else {
			test_cmplt_epi8_asm_256(a, b, which, ans)
		}
		if prev != nil {
			if s := cmp.Diff(prev, ans); s != "" {
				t.Fatalf("cmplt returned different result for which=%d\n%s", which, s)
			}
		}
		prev = bytes.Clone(ans)
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

func get_sizes(t *testing.T) []int {
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
	return sizes
}

func addressof_data(b []byte) uintptr {
	return uintptr(unsafe.Pointer(&b[0]))
}

func memset(ans []byte, val byte) {
	for i := range ans {
		ans[i] = val
	}
}

func aligned_slice(sz, alignment int) ([]byte, []byte) {
	ans := make([]byte, sz+alignment+512)
	a := addressof_data(ans)
	a &= uintptr(alignment - 1)
	extra := uintptr(alignment) - a
	memset(ans, '<')
	memset(ans[extra+uintptr(sz):], '>')
	return ans[extra : extra+uintptr(sz)], ans
}

func TestSIMDStringOps(t *testing.T) {
	sizes := get_sizes(t)
	test := func(haystack []byte, a, b byte, align_offset int) {
		var actual int
		sh, _ := aligned_slice(len(haystack)+align_offset, 64)
		sh = sh[align_offset:]
		copy(sh, haystack)
		haystack = sh
		expected := index_byte2_scalar(haystack, a, b)

		for _, sz := range sizes {
			switch sz {
			case 16:
				actual = index_byte2_asm_128(haystack, a, b)
			case 32:
				actual = index_byte2_asm_256(haystack, a, b)
			}
			if actual != expected {
				t.Fatalf("Failed to find '%c' or '%c' in: %#v at align: %d (expected: %d != actual: %d) at size: %d",
					a, b, string(haystack), addressof_data(haystack)&uintptr(sz-1), expected, actual, sz)
			}
		}

	}
	// test alignment issues
	q := []byte("abc")
	for sz := 0; sz < 32; sz++ {
		test(q, '<', '>', sz)
		test(q, ' ', 'b', sz)
		test(q, '<', 'a', sz)
		test(q, '<', 'b', sz)
		test(q, 'c', '>', sz)
	}

	tests := func(h string, a, b byte) {
		for _, sz := range []int{0, 16, 32, 64, 79} {
			q := strings.Repeat(" ", sz) + h
			for sz := 0; sz < 32; sz++ {
				test([]byte(q), a, b, sz)
			}
		}
	}
	test(nil, '<', '>', 1)
	test([]byte{}, '<', '>', 1)

	tests("", '<', '>')
	tests("a", 0, 0)
	tests("a", '<', '>')
	tests("dsdfsfa", '1', 'a')
	tests("xa", 'a', 'a')
	tests("bbb", 'a', '1')
	tests("bba", 'a', '<')
	tests("baa", '>', 'a')

	c0test := func(haystack []byte) {
		var actual int
		safe_haystack := append(bytes.Repeat([]byte{'<'}, 64), haystack...)
		safe_haystack = append(safe_haystack, bytes.Repeat([]byte{'>'}, 64)...)
		haystack = safe_haystack[64 : 64+len(haystack)]
		expected := index_c0_scalar(haystack)

		for _, sz := range sizes {
			switch sz {
			case 16:
				actual = index_c0_asm_128(haystack)
			case 32:
				actual = index_c0_asm_256(haystack)
			}
			if actual != expected {
				t.Fatalf("C0 char index failed in: %#v (%d != %d) at size: %d", string(haystack), expected, actual, sz)
			}
		}

	}

	c0tests := func(h string) {
		c0test([]byte(h))
		for _, sz := range []int{16, 32, 64, 79} {
			q := strings.Repeat(" ", sz) + h
			c0test([]byte(q))
		}
	}

	c0tests("a\nfgdfgd\r")
	c0tests("")
	c0tests("abcdef")
	c0tests("afsgdfg\x7f")
	c0tests("afgd\x1bfgd\t")
	c0tests("a\x00")

	index_test := func(haystack []byte, needle byte) {
		var actual int
		expected := index_byte_scalar(haystack, needle)

		for _, sz := range sizes {
			switch sz {
			case 16:
				actual = index_byte_asm_128(haystack, needle)
			case 32:
				actual = index_byte_asm_256(haystack, needle)
			}
			if actual != expected {
				t.Fatalf("index failed in: %#v (%d != %d) at size: %d with needle: %#v", string(haystack), expected, actual, sz, needle)
			}
		}
	}
	index_test([]byte("abc"), 'x')
	index_test([]byte("abc"), 'b')

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
		for _, b := range []byte{1, 0b110111, 0xff, 0, ' '} {
			ae(sz, `set1_epi8_test`, broadcast_byte(b, sz), test_set1_epi8(b, sz))
		}
		ae(sz, `set1_epi8_test`, broadcast_byte(0xff, sz), test_set1_epi8(11, sz))
	})
	tests = append(tests, func(sz int) {
		a := ordered_bytes(sz)
		b := ordered_bytes(sz)
		ans := test_cmpeq_epi8(a, b)
		ae(sz, `cmpeq_epi8_test`, broadcast_byte(0xff, sz), ans)

		lt := func(a, b []byte) []byte {
			ans := make([]byte, len(a))
			for i := range ans {
				if int8(a[i]) < int8(b[i]) {
					ans[i] = 0xff
				}
			}
			return ans
		}

		ae(sz, "cmplt_epi8_test with equal vecs of non-negative numbers", lt(a, b), test_cmplt_epi8(t, a, b))
		a = broadcast_byte(1, sz)
		b = broadcast_byte(2, sz)
		ae(sz, "cmplt_epi8_test with 1 and 2", lt(a, b), test_cmplt_epi8(t, a, b))
		ae(sz, "cmplt_epi8_test with 2 and 1", lt(b, a), test_cmplt_epi8(t, b, a))
		a = broadcast_byte(0xff, sz)
		b = broadcast_byte(0, sz)
		ae(sz, "cmplt_epi8_test with -1 and 0", lt(a, b), test_cmplt_epi8(t, a, b))
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

	sizes := get_sizes(t)
	for _, sz := range sizes {
		for _, test := range tests {
			test(sz)
		}
	}

}
