// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"cmp"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/simdstring"
	"golang.org/x/exp/constraints"
	"golang.org/x/text/language"
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

func Format_stacktrace_on_panic(r any) (text string, err error) {
	pcs := make([]uintptr, 512)
	n := runtime.Callers(3, pcs)
	lines := []string{}
	frames := runtime.CallersFrames(pcs[:n])
	err = fmt.Errorf("Panicked: %s", r)
	lines = append(lines, fmt.Sprintf("\r\nPanicked with error: %s\r\nStacktrace (most recent call first):\r\n", r))
	found_first_frame := false
	for frame, more := frames.Next(); more; frame, more = frames.Next() {
		if !found_first_frame {
			if strings.HasPrefix(frame.Function, "runtime.") {
				continue
			}
			found_first_frame = true
		}
		lines = append(lines, fmt.Sprintf("%s\r\n\t%s:%d\r\n", frame.Function, frame.File, frame.Line))
	}
	text = strings.Join(lines, "")
	return strings.TrimSpace(text), err
}

// Run the specified function in parallel over chunks from the specified range.
// If the function panics, it is turned into a regular error.
func Run_in_parallel_over_range(num_procs int, f func(int, int) error, start, limit int) (err error) {
	num_items := limit - start
	if num_procs <= 0 {
		num_procs = runtime.NumCPU()
	}
	num_procs = max(1, min(num_procs, num_items))
	if num_procs < 2 {
		defer func() {
			if r := recover(); r != nil {
				stacktrace, e := Format_stacktrace_on_panic(r)
				err = fmt.Errorf("%s\n\n%w", stacktrace, e)
			}
		}()
		return f(start, limit)
	}
	chunk_sz := max(1, num_items/num_procs)
	var wg sync.WaitGroup
	echan := make(chan error, num_procs)
	for start < limit {
		end := min(start+chunk_sz, limit)
		wg.Add(1)
		go func(start, end int) {
			defer func() {
				if r := recover(); r != nil {
					stacktrace, e := Format_stacktrace_on_panic(r)
					echan <- fmt.Errorf("%s\n\n%w", stacktrace, e)
				}
				wg.Done()
			}()
			if err := f(start, end); err != nil {
				echan <- err
			}
		}(start, end)
		start = end
	}
	wg.Wait()
	close(echan)
	for qerr := range echan {
		return qerr
	}
	return

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
	for i := range n {
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

func Uniq[T comparable](s []T) []T {
	seen := NewSet[T](len(s))
	ans := make([]T, 0, len(s))
	for _, x := range s {
		if !seen.Has(x) {
			seen.Add(x)
			ans = append(ans, x)
		}
	}
	return ans
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

func Abs[T constraints.Integer](x T) T {
	if x < 0 {
		return -x
	}
	return x
}

var LanguageTag = sync.OnceValue(func() language.Tag {
	// Check environment variables in order of precedence
	var locale string
	for _, v := range []string{"LC_ALL", "LC_MESSAGES", "LANG"} {
		locale = os.Getenv(v)
		if locale != "" {
			break
		}
	}
	if locale == "" {
		return language.English // Default/fallback
	}
	// Remove encoding, e.g., ".UTF-8"
	locale = strings.Split(locale, ".")[0]
	// Replace underscore with hyphen to match BCP47 format (en_US -> en-US)
	locale = strings.ReplaceAll(locale, "_", "-")
	// Validate/normalize with golang.org/x/text/language
	tag, err := language.Parse(locale)
	if err != nil {
		return language.English
	}
	return tag

})

// Replace control codes by unicode codepoints that describe the codes
// making the text safe to send to a terminal
func ReplaceControlCodes(text, replace_tab_by, replace_newline_by string) string {
	buf := strings.Builder{}
	for len(text) > 0 {
		idx := simdstring.IndexC0String(text)
		if idx < 0 {
			if buf.Cap() == 0 {
				return text
			}
			buf.WriteString(text)
			break
		}
		if buf.Cap() == 0 {
			buf.Grow(2 * len(text))
		}
		buf.WriteString(text[:idx])
		switch text[idx] {
		case '\n':
			buf.WriteString(replace_newline_by)
		case '\t':
			buf.WriteString(replace_tab_by)
		case 0x7f:
			buf.WriteRune(0x2421)
		default:
			buf.WriteRune(0x2400 + rune(text[idx]))
		}
		text = text[idx+1:]
	}
	return buf.String()
}
