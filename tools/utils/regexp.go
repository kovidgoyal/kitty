// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"regexp"
	"strings"
	"sync"
)

var _ = fmt.Print

var pat_cache = map[string]*regexp.Regexp{}
var pat_cache_lock = sync.RWMutex{}

func ReplaceAll(pat, str string, repl func(full_match string, groupdict map[string]string) string) string {
	pat_cache_lock.RLock()
	cpat := pat_cache[pat]
	pat_cache_lock.RUnlock()
	if cpat == nil {
		cpat = regexp.MustCompile(pat)
		pat_cache_lock.Lock()
		pat_cache[pat] = cpat
		pat_cache_lock.Unlock()
	}
	result := strings.Builder{}
	result.Grow(len(str) + 256)
	last_index := 0
	matches := cpat.FindAllStringSubmatchIndex(str, -1)
	names := cpat.SubexpNames()
	for _, v := range matches {
		match_start, match_end := v[0], v[1]
		full_match := str[match_start:match_end]
		groupdict := make(map[string]string, len(names))
		for i, name := range names {
			if i == 0 {
				continue
			}
			idx := 2 * i
			if v[idx] > -1 && v[idx+1] > -1 {
				groupdict[name] = str[v[idx]:v[idx+1]]
			}
		}
		result.WriteString(str[last_index:match_start])
		result.WriteString(repl(full_match, groupdict))
		last_index = match_end
	}
	result.WriteString(str[last_index:])
	return result.String()
}
