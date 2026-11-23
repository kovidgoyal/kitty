// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

//go:build !goexperiment.simd

package simdstring

// Without GOEXPERIMENT=simd the simd package is unavailable, the scalar
// implementations are used.

const HasSIMDCode = false

func simd_vector_size() int { return 0 }

// SIMD implementations available at runtime, fastest first
func simd_impls() []*impl_set { return nil }

func portable_impl() *impl_set { return nil }
