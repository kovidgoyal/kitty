// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
)

var _ = fmt.Print

func Reverse[T any](s []T) {
	for i, j := 0, len(s)-1; i < j; i, j = i+1, j-1 {
		s[i], s[j] = s[j], s[i]
	}
}

func Reversed[T any](s []T) []T {
	ans := make([]T, len(s))
	for i, x := range s {
		ans[len(s)-1-i] = x
	}
	return ans
}
