// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"regexp"
	"strings"
	"sync"
)

var _ = fmt.Print

type UnboundedCache[K comparable, V any] struct {
	data map[K]V
	lock sync.RWMutex
}

func NewUnboundedCache[K comparable, V any]() *UnboundedCache[K, V] {
	ans := UnboundedCache[K, V]{data: map[K]V{}}
	return &ans
}

func (self *UnboundedCache[K, V]) GetOrCreate(key K, create func(key K) (V, error)) (V, error) {
	self.lock.RLock()
	ans, found := self.data[key]
	self.lock.RUnlock()
	if found {
		return ans, nil
	}
	ans, err := create(key)
	if err == nil {
		self.lock.Lock()
		self.data[key] = ans
		self.lock.Unlock()
	}
	return ans, err
}

func (self *UnboundedCache[K, V]) MustGetOrCreate(key K, create func(key K) V) V {
	self.lock.RLock()
	ans, found := self.data[key]
	self.lock.RUnlock()
	if found {
		return ans
	}
	ans = create(key)
	self.lock.Lock()
	self.data[key] = ans
	self.lock.Unlock()
	return ans
}

var pat_cache = NewUnboundedCache[string, *regexp.Regexp]()

func ReplaceAll(pat, str string, repl func(full_match string, groupdict map[string]string) string) string {
	cpat := pat_cache.MustGetOrCreate(pat, regexp.MustCompile)
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
