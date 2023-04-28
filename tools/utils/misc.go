// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"os"

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
		var zero T
		s[idx] = zero // if pointer this allows garbage collection
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

func Map[T any, O any](f func(x T) O, s []T) []O {
	ans := make([]O, 0, len(s))
	for _, x := range s {
		ans = append(ans, f(x))
	}
	return ans
}

func Repeat[T any](x T, n int) []T {
	ans := make([]T, n)
	for i := 0; i < n; i++ {
		ans[i] = x
	}
	return ans
}

func Sort[T any](s []T, less func(a, b T) bool) []T {
	slices.SortFunc(s, less)
	return s
}

func StableSort[T any](s []T, less func(a, b T) bool) []T {
	slices.SortStableFunc(s, less)
	return s
}

func sort_with_key[T any, C constraints.Ordered](stable bool, s []T, key func(a T) C) []T {
	type t struct {
		key C
		val T
	}
	temp := make([]t, len(s))
	for i, x := range s {
		temp[i].val, temp[i].key = x, key(x)
	}
	if stable {
		slices.SortStableFunc(temp, func(a, b t) bool { return a.key < b.key })
	} else {
		slices.SortFunc(temp, func(a, b t) bool { return a.key < b.key })
	}
	for i, x := range temp {
		s[i] = x.val
	}
	return s
}

func SortWithKey[T any, C constraints.Ordered](s []T, key func(a T) C) []T {
	return sort_with_key(false, s, key)
}

func StableSortWithKey[T any, C constraints.Ordered](s []T, key func(a T) C) []T {
	return sort_with_key(true, s, key)
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

type statable interface {
	Stat() (os.FileInfo, error)
}

func Samefile(a, b any) bool {
	var sta, stb os.FileInfo
	var err error
	switch v := a.(type) {
	case string:
		sta, err = os.Stat(v)
		if err != nil {
			return false
		}
	case statable:
		sta, err = v.Stat()
		if err != nil {
			return false
		}
	case *os.FileInfo:
		sta = *v
	case os.FileInfo:
		sta = v
	default:
		panic(fmt.Sprintf("a must be a string, os.FileInfo or a stat-able object not %T", v))
	}
	switch v := b.(type) {
	case string:
		stb, err = os.Stat(v)
		if err != nil {
			return false
		}
	case statable:
		stb, err = v.Stat()
		if err != nil {
			return false
		}
	case *os.FileInfo:
		stb = *v
	case os.FileInfo:
		stb = v
	default:
		panic(fmt.Sprintf("b must be a string, os.FileInfo or a stat-able object not %T", v))
	}

	return os.SameFile(sta, stb)
}

func Concat[T any](slices ...[]T) []T {
	var total int
	for _, s := range slices {
		total += len(s)
	}
	result := make([]T, total)
	var i int
	for _, s := range slices {
		i += copy(result[i:], s)
	}
	return result
}
