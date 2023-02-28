// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"sort"

	"golang.org/x/exp/constraints"
	"golang.org/x/exp/slices"
)

var _ = fmt.Print

func Reverse[T any](s []T) []T {
	for i, j := 0, len(s)-1; i < j; i, j = i+1, j-1 {
		s[i], s[j] = s[j], s[i]
	}
	return s
}

func Reversed[T any](s []T) []T {
	ans := make([]T, len(s))
	for i, x := range s {
		ans[len(s)-1-i] = x
	}
	return ans
}

func Remove[T comparable](s []T, q T) []T {
	idx := slices.Index(s, q)
	if idx > -1 {
		return slices.Delete(s, idx, idx+1)
	}
	return s
}

func RemoveAll[T comparable](s []T, q T) []T {
	ans := s
	for {
		idx := slices.Index(ans, q)
		if idx < 0 {
			break
		}
		ans = slices.Delete(ans, idx, idx+1)
	}
	return ans
}

func Filter[T any](s []T, f func(x T) bool) []T {
	ans := make([]T, 0, len(s))
	for _, x := range s {
		if f(x) {
			ans = append(ans, x)
		}
	}
	return ans
}

func Map[T any](s []T, f func(x T) T) []T {
	ans := make([]T, 0, len(s))
	for _, x := range s {
		ans = append(ans, f(x))
	}
	return ans
}

func Sort[T any](s []T, less func(a, b T) bool) []T {
	sort.Slice(s, func(i, j int) bool { return less(s[i], s[j]) })
	return s
}

func StableSort[T any](s []T, less func(a, b T) bool) []T {
	sort.SliceStable(s, func(i, j int) bool { return less(s[i], s[j]) })
	return s
}

func SortWithKey[T any, C constraints.Ordered](s []T, key func(a T) C) []T {
	mem := make([]C, len(s))
	for i, x := range s {
		mem[i] = key(x)
	}
	sort.Slice(s, func(i, j int) bool { return mem[i] < mem[j] })
	return s
}

func StableSortWithKey[T any, C constraints.Ordered](s []T, key func(a T) C) []T {
	mem := make([]C, len(s))
	for i, x := range s {
		mem[i] = key(x)
	}
	sort.SliceStable(s, func(i, j int) bool { return mem[i] < mem[j] })
	return s
}

func Max[T constraints.Ordered](a T, items ...T) (ans T) {
	ans = a
	for _, q := range items {
		if q > ans {
			ans = q
		}
	}
	return ans
}

func Min[T constraints.Ordered](a T, items ...T) (ans T) {
	ans = a
	for _, q := range items {
		if q < ans {
			ans = q
		}
	}
	return ans
}

func Index[T comparable](haystack []T, needle T) int {
	for i, x := range haystack {
		if x == needle {
			return i
		}
	}
	return -1
}

func Contains[T comparable](haystack []T, needle T) bool {
	return Index(haystack, needle) > -1
}

// Keys returns the keys of the map m.
// The keys will be an indeterminate order.
func Keys[M ~map[K]V, K comparable, V any](m M) []K {
	r := make([]K, len(m))
	i := 0
	for k := range m {
		r[i] = k
		i++
	}
	return r
}

// Values returns the values of the map m.
// The values will be an indeterminate order.
func Values[M ~map[K]V, K comparable, V any](m M) []V {
	r := make([]V, len(m))
	i := 0
	for _, v := range m {
		r[i] = v
		i++
	}
	return r
}

func Memset[T any](dest []T, pattern ...T) []T {
	if len(pattern) == 0 {
		var zero T
		switch any(zero).(type) {
		case byte: // special case this as the compiler can generate efficient code for memset of a byte slice to zero
			bd := any(dest).([]byte)
			for i := range bd {
				bd[i] = 0
			}
		default:
			for i := range dest {
				dest[i] = zero
			}
		}
		return dest
	}
	bp := copy(dest, pattern)
	for bp < len(dest) {
		copy(dest[bp:], dest[:bp])
		bp *= 2
	}
	return dest
}
