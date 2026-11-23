// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

//go:build goexperiment.simd && !amd64 && !arm64

package simdstring

import "simd"

// SIMD implementations available at runtime, fastest first
func simd_impls() []*impl_set {
	if simd_vector_size() == 0 {
		// emulated, slower than scalar code
		return nil
	}
	return []*impl_set{portable_impl()}
}

func first_true(m simd.Mask8s) int  { return first_true_portable(m) }
func first_false(m simd.Mask8s) int { return first_false_portable(m) }
