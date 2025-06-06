package fzf

import (
	"fmt"
)

var _ = fmt.Print

func NewFuzzyMatcher(scheme Scheme) (ans *FuzzyMatcher) {
	return new_fuzzy_matcher(scheme)
}

// Score the specified items using runtime.NumCPU() go routines. This function
// reports a panic in any worker go routine as a regular error.
func (m *FuzzyMatcher) Score(items []string, pattern string) (ans []Result, err error) {
	return m.score(items, pattern, func(item string, pat []rune, pattern_is_ascii bool, slab *slab, as_chars func(string) Chars) Result {
		c := as_chars(item)
		return m.score_one(&c, pat, pattern_is_ascii, slab)
	})
}

// Clear the cache used ScoreWithCache(). Useful if you change some of the
// settings used for scoring.
func (m *FuzzyMatcher) ClearScoreCache() {
	m.cache_mutex.Lock()
	m.cache = make(map[string]Result)
	m.cache_mutex.Unlock()
}

// Same as Score, except that it uses a cache. Remember to call
// ClearScoreCache() if you change any scoring settings on this FuzzyMatcher.
func (m *FuzzyMatcher) ScoreWithCache(items []string, pattern string) (ans []Result, err error) {
	key_prefix := pattern + "\x00"
	return m.score(items, pattern, func(item string, pat []rune, pattern_is_ascii bool, slab *slab, as_chars func(string) Chars) Result {
		key := key_prefix + item
		m.cache_mutex.Lock()
		res, found := m.cache[key]
		m.cache_mutex.Unlock()
		if !found {
			c := as_chars(item)
			res = m.score_one(&c, pat, pattern_is_ascii, slab)
			m.cache_mutex.Lock()
			m.cache[key] = res
			m.cache_mutex.Unlock()
		}
		return res
	})
}
