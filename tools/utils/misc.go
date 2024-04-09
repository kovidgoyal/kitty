// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"cmp"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strconv"

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

func Sort[T any](s []T, cmp func(a, b T) int) []T {
	slices.SortFunc(s, cmp)
	return s
}

func StableSort[T any](s []T, cmp func(a, b T) int) []T {
	slices.SortStableFunc(s, cmp)
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
	key_cmp := func(a, b t) int {
		return cmp.Compare(a.key, b.key)
	}
	if stable {
		slices.SortStableFunc(temp, key_cmp)
	} else {
		slices.SortFunc(temp, key_cmp)
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
	switch len(pattern) {
	case 0:
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
	case 1:
		val := pattern[0]
		for i := range dest {
			dest[i] = val
		}
	default:
		bp := copy(dest, pattern)
		for bp < len(dest) {
			copy(dest[bp:], dest[:bp])
			bp *= 2
		}
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

func ShiftLeft[T any](s []T, amt int) []T {
	leftover := len(s) - amt
	if leftover > 0 {
		copy(s, s[amt:])
	}
	return s[:leftover]
}

func SetStructDefaults(v reflect.Value) (err error) {
	for _, field := range reflect.VisibleFields(v.Type()) {
		if defval := field.Tag.Get("default"); defval != "" {
			val := v.FieldByIndex(field.Index)
			if val.CanSet() {
				switch field.Type.Kind() {
				case reflect.String:
					if val.String() != "" {
						val.SetString(defval)
					}
				case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
					if d, err := strconv.ParseInt(defval, 10, 64); err == nil {
						val.SetInt(d)
					} else {
						return fmt.Errorf("Could not parse default value for struct field: %#v with error: %s", field.Name, err)
					}
				case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
					if d, err := strconv.ParseUint(defval, 10, 64); err == nil {
						val.SetUint(d)
					} else {
						return fmt.Errorf("Could not parse default value for struct field: %#v with error: %s", field.Name, err)
					}

				}
			}
		}
	}
	return
}

func IfElse[T any](condition bool, if_val T, else_val T) T {
	if condition {
		return if_val
	}
	return else_val
}

func SourceLine(skip_frames ...int) int {
	s := 1
	if len(skip_frames) > 0 {
		s += skip_frames[0]
	}
	if _, _, ans, ok := runtime.Caller(s); ok {
		return ans
	}
	return -1
}

func SourceLoc(skip_frames ...int) string {
	s := 1
	if len(skip_frames) > 0 {
		s += skip_frames[0]
	}
	if _, file, line, ok := runtime.Caller(s); ok {
		return filepath.Base(file) + ":" + strconv.Itoa(line)
	}
	return "unknown"
}

func FunctionName(a any) string {
	if a == nil {
		return "<nil>"
	}
	p := reflect.ValueOf(a).Pointer()
	f := runtime.FuncForPC(p)
	if f != nil {
		return f.Name()
	}
	return ""
}
