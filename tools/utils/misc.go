// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"sort"

	"golang.org/x/exp/constraints"
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
