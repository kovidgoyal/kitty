// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"math"
)

var _ = fmt.Print

func slice_iter(strs []string) func() (string, bool) {
	i := 0
	limit := len(strs)
	return func() (string, bool) {
		if i < limit {
			i++
			return strs[i-1], false
		}
		return "", true
	}
}

// Prefix returns the longest common prefix of the provided strings
func Prefix(strs []string) string {
	return LongestCommon(slice_iter(strs), true)
}

// Suffix returns the longest common suffix of the provided strings
func Suffix(strs []string) string {
	return LongestCommon(slice_iter(strs), false)
}

func min(a ...int) int {
	ans := math.MaxInt
	for _, x := range a {
		if x < ans {
			ans = x
		}
	}
	return ans
}

func LongestCommon(next func() (string, bool), prefix bool) string {
	xfix, done := next()
	if xfix == "" || done {
		return ""
	}
	for {
		q, done := next()
		if done {
			break
		}
		q_len := len(q)
		xfix_len := len(xfix)
		max_len := min(q_len, xfix_len)
		if max_len == 0 {
			return ""
		}
		if prefix {
			for i := 0; i < max_len; i++ {
				if xfix[i] != q[i] {
					xfix = xfix[:i]
					break
				}
			}
		} else {
			for i := 0; i < max_len; i++ {
				xi := xfix_len - i - 1
				si := q_len - i - 1
				if xfix[xi] != q[si] {
					xfix = xfix[xi+1:]
					break
				}
			}
		}
	}
	return xfix
}
