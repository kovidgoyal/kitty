// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package simdstring

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"testing"
	"unsafe"
)

var _ = fmt.Print

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

var impls_to_test []*impl_set

func get_impls_to_test() []*impl_set {
	if impls_to_test == nil {
		impls_to_test = simd_impls()
		if HasSIMDCode && simd_vector_size() == 0 {
			// test the emulated implementation as well
			impls_to_test = append(impls_to_test, portable_impl())
		}
	}
	return impls_to_test
}

// Compare the SIMD and scalar implementations of every function. t.Helper()
// is expensive as it walks the stack, so it is called only when reporting a
// failure, not on every one of the millions of checks.
func check_all(t *testing.T, haystack []byte, a, b byte) {
	text := string(haystack)
	s := scalar_impl()
	for _, i := range get_impls_to_test() {
		for _, r := range [...]struct {
			name             string
			expected, actual int
		}{
			{"IndexByte", s.index_byte(haystack, a), i.index_byte(haystack, a)},
			{"IndexByteString", s.index_byte_string(text, a), i.index_byte_string(text, a)},
			{"IndexByte2", s.index_byte2(haystack, a, b), i.index_byte2(haystack, a, b)},
			{"IndexByte2String", s.index_byte2_string(text, a, b), i.index_byte2_string(text, a, b)},
			{"IndexC0", s.index_c0(haystack), i.index_c0(haystack)},
			{"IndexC0String", s.index_c0_string(text), i.index_c0_string(text)},
			{"NotIndexByte", s.not_index_byte(haystack, a), i.not_index_byte(haystack, a)},
			{"NotIndexByteString", s.not_index_byte_string(text, a), i.not_index_byte_string(text, a)},
			{"NotIndexByte2", s.not_index_byte2(haystack, a, b), i.not_index_byte2(haystack, a, b)},
			{"NotIndexByte2String", s.not_index_byte2_string(text, a, b), i.not_index_byte2_string(text, a, b)},
		} {
			if r.actual != r.expected {
				t.Helper()
				t.Fatalf("%s %s failed in: %#v (expected: %d != actual: %d) with needles: %#v, %#v at vector size: %d",
					i.name, r.name, text, r.expected, r.actual, a, b, simd_vector_size())
			}
		}
	}
}

func TestSIMDStringOps(t *testing.T) {
	// run concurrently with the sub-processes of TestSIMDStringOpsAllVectorSizes
	t.Parallel()
	if len(get_impls_to_test()) == 0 {
		t.Skip("No SIMD implementations available")
	}
	test := func(haystack []byte, a, b byte, align_offset int) {
		t.Helper()
		sh, _ := aligned_slice(len(haystack)+align_offset, 64)
		sh = sh[align_offset:]
		copy(sh, haystack)
		check_all(t, sh, a, b)
	}
	// test alignment issues
	q := []byte("abc")
	for sz := range 64 {
		test(q, '<', '>', sz)
		test(q, ' ', 'b', sz)
		test(q, '<', 'a', sz)
		test(q, '<', 'b', sz)
		test(q, 'c', '>', sz)
	}

	tests := func(h string, a, b byte) {
		t.Helper()
		for _, sz := range []int{0, 15, 16, 17, 31, 32, 33, 63, 64, 65, 79, 128, 200} {
			q := strings.Repeat(" ", sz) + h
			for align := range 64 {
				test([]byte(q), a, b, align)
			}
		}
	}
	check_all(t, nil, '<', '>')
	check_all(t, []byte{}, '<', '>')

	tests("", '<', '>')
	tests("a", 0, 0)
	tests("a", '<', '>')
	tests("dsdfsfa", '1', 'a')
	tests("xa", 'a', 'a')
	tests("bbb", 'a', '1')
	tests("bba", 'a', '<')
	tests("baa", '>', 'a')
	tests("baa", ' ', 'a')
	tests("a\nfgdfgd\r", ' ', 0)
	tests("afsgdfg\x7f", ' ', '\x7f')
	tests("afgd\x1bfgd\t", 'a', 'f')
	tests("a\x00", 0, ' ')
	tests("\x80\xff\x1f\x20\x7e", 0xff, 0x80)

	// A single distinct byte at every position in haystacks of every size
	// up to a few vectors long, including the case of 0 bytes, which are
	// used to fill partial loads.
	// These are the bulk of the checks, so run them in parallel.
	for _, filler := range []byte{'a', 0, 0xff} {
		for _, needle := range []byte{'q', 0, 0x7f, 0x1f, 0xff} {
			if needle == filler {
				continue
			}
			t.Run(fmt.Sprintf("filler=%#x,needle=%#x", filler, needle), func(t *testing.T) {
				t.Parallel()
				for sz := range 3*64 + 2 {
					h := bytes.Repeat([]byte{filler}, sz)
					check_all(t, h, needle, filler)
					check_all(t, h, filler, needle)
					for pos := range sz {
						h[pos] = needle
						check_all(t, h, needle, filler)
						check_all(t, h, filler, needle)
						check_all(t, h, needle, 'z')
						check_all(t, h, filler, 'z')
						h[pos] = filler
					}
				}
			})
		}
	}
}

const vector_size_env_var = "KITTY_SIMDSTRING_TEST_VECTOR_SIZE"

// Run TestSIMDStringOps in a sub-process for every vector size, including
// emulation, supported by this CPU, as the size is fixed at program start.
func TestSIMDStringOpsAllVectorSizes(t *testing.T) {
	if !HasSIMDCode {
		t.Skip("built without GOEXPERIMENT=simd")
	}
	if q := os.Getenv(vector_size_env_var); q != "" {
		t.Skip("already running in a sub-process with vector size: " + q)
	}
	// The native vector size is tested by TestSIMDStringOps in this process
	sizes := []int{0}
	for _, sz := range []int{16, 32, 64} {
		if sz < simd_vector_size() {
			sizes = append(sizes, sz)
		}
	}
	for _, sz := range sizes {
		t.Run(fmt.Sprintf("vector_size=%d", sz), func(t *testing.T) {
			t.Parallel()
			cmd := exec.Command(os.Args[0], "-test.run=^TestSIMDStringOps$", "-test.count=1")
			// The leading + allows using a size even if the CPU does not
			// support every operation in the simd package at that size
			cmd.Env = append(os.Environ(), fmt.Sprintf("GODEBUG=simd=+%d", sz*8), fmt.Sprintf("%s=%d", vector_size_env_var, sz))
			out, err := cmd.CombinedOutput()
			if err != nil {
				t.Fatalf("Running tests with vector size: %d failed with error: %s and output:\n%s", sz, err, out)
			}
			if !bytes.Contains(out, []byte("PASS")) {
				t.Fatalf("Running tests with vector size: %d produced unexpected output:\n%s", sz, out)
			}
		})
	}
}

func TestSIMDDispatch(t *testing.T) {
	if q := os.Getenv(vector_size_env_var); q != "" {
		if expected := fmt.Sprint(simd_vector_size()); q != expected {
			t.Fatalf("Vector size is %s instead of requested: %s", expected, q)
		}
	}
	if !HasSIMDCode {
		if VectorSize != 1 || Have128bit {
			t.Fatalf("SIMD reported as in use when built without it")
		}
		return
	}
	// NEON is mandatory on arm64
	if runtime.GOARCH == "arm64" {
		if os.Getenv(vector_size_env_var) == "" && !Have128bit {
			t.Fatalf("SIMD support not available at runtime")
		}
	}
	if Have128bit && VectorSize != simd_vector_size() {
		t.Fatalf("VectorSize: %d != %d", VectorSize, simd_vector_size())
	}
}
