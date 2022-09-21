// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"regexp"
	"strings"
)

var _ = fmt.Print

var pat_cache = NewLRUCache[string, *regexp.Regexp](128)

type SubMatch struct {
	Text       string
	Start, End int
}

func Compile(pat string) (*regexp.Regexp, error) {
	return pat_cache.GetOrCreate(pat, regexp.Compile)
}

func MustCompile(pat string) *regexp.Regexp {
	return pat_cache.MustGetOrCreate(pat, regexp.MustCompile)
}

func ReplaceAll(pat, str string, repl func(full_match string, groupdict map[string]SubMatch) string) string {
	cpat := MustCompile(pat)
	result := strings.Builder{}
	result.Grow(len(str) + 256)
	last_index := 0
	matches := cpat.FindAllStringSubmatchIndex(str, -1)
	names := cpat.SubexpNames()
	for _, v := range matches {
		match_start, match_end := v[0], v[1]
		full_match := str[match_start:match_end]
		groupdict := make(map[string]SubMatch, len(names))
		for i, name := range names {
			if i == 0 {
				continue
			}
			idx := 2 * i
			if v[idx] > -1 && v[idx+1] > -1 {
				groupdict[name] = SubMatch{Text: str[v[idx]:v[idx+1]], Start: v[idx] - match_start, End: v[idx+1] - match_start}
			}
		}
		result.WriteString(str[last_index:match_start])
		result.WriteString(repl(full_match, groupdict))
		last_index = match_end
	}
	result.WriteString(str[last_index:])
	return result.String()
}
