// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package subseq

import (
	"fmt"
	"slices"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

const (
	LEVEL1 = "/"
	LEVEL2 = "-_0123456789"
	LEVEL3 = "."
)

type resolved_options_type struct {
	level1, level2, level3 []rune
}

type Options struct {
	Level1, Level2, Level3 string
	NumberOfThreads        int
}

type Match struct {
	Positions []int
	Score     float64
	idx       int
	Text      string
}

func level_factor_for(current_lcase, last_lcase, current_cased, last_cased rune, opts *resolved_options_type) int {
	switch {
	case slices.Contains(opts.level1, last_lcase):
		return 90
	case slices.Contains(opts.level2, last_lcase):
		return 80
	case last_lcase == last_cased && current_lcase != current_cased: // camelCase
		return 80
	case slices.Contains(opts.level3, last_lcase):
		return 70
	default:
		return 0
	}
}

type workspace_type struct {
	positions          [][]int // positions of each needle char in haystack
	level_factors      []int
	address            []int
	max_score_per_char float64
}

func (w *workspace_type) initialize(haystack_sz, needle_sz int) {
	if cap(w.positions) < needle_sz {
		w.positions = make([][]int, needle_sz)
	} else {
		w.positions = w.positions[:needle_sz]
	}
	if cap(w.level_factors) < haystack_sz {
		w.level_factors = make([]int, 2*haystack_sz)
	} else {
		w.level_factors = w.level_factors[:haystack_sz]
	}
	for i, s := range w.positions {
		if cap(s) < haystack_sz {
			w.positions[i] = make([]int, 0, 2*haystack_sz)
		} else {
			w.positions[i] = w.positions[i][:0]
		}
	}
	if cap(w.address) < needle_sz {
		w.address = make([]int, needle_sz)
	}
	w.address = utils.Memset(w.address)
}

func (w *workspace_type) position(x int) int { // the position of xth needle char in the haystack for the current address
	return w.positions[x][w.address[x]]
}

func (w *workspace_type) increment_address() bool {
	pos := len(w.positions) - 1 // the last needle char
	for {
		w.address[pos]++
		if w.address[pos] < len(w.positions[pos]) {
			return true
		}
		if pos == 0 {
			break
		}
		w.address[pos] = 0
		pos--
	}
	return false
}

func (w *workspace_type) address_is_monotonic() bool {
	// Check if the character positions pointed to by the current address are monotonic
	for i := 1; i < len(w.positions); i++ {
		if w.position(i) <= w.position(i-1) {
			return false
		}
	}
	return true
}

func (w *workspace_type) calc_score() (ans float64) {
	distance, pos := 0, 0
	for i := range len(w.positions) {
		pos = w.position(i)
		if i == 0 {
			distance = pos + 1
		} else {
			distance = pos - w.position(i-1)
			if distance < 2 {
				ans += w.max_score_per_char // consecutive chars
				continue
			}
		}
		if w.level_factors[pos] > 0 {
			ans += (100.0 * w.max_score_per_char) / float64(w.level_factors[pos]) // at a special location
		} else {
			ans += (0.75 * w.max_score_per_char) / float64(distance)
		}
	}
	return
}

func has_atleast_one_match(w *workspace_type) (found bool) {
	p := -1
	for i := range len(w.positions) {
		if len(w.positions[i]) == 0 { // all chars of needle not in haystack
			return false
		}
		found = false
		for _, pos := range w.positions[i] {
			if pos > p {
				p = pos
				found = true
				break
			}
		}
		if !found { // chars of needle not present in sequence in haystack
			return false
		}
	}
	return true
}

func score_item(item string, idx int, needle []rune, opts *resolved_options_type, w *workspace_type) *Match {
	ans := &Match{idx: idx, Text: item, Positions: make([]int, len(needle))}
	haystack := []rune(strings.ToLower(item))
	orig_haystack := []rune(item)
	w.initialize(len(orig_haystack), len(needle))
	for i := range len(haystack) {
		level_factor_calculated := false
		for j := range len(needle) {
			if needle[j] == haystack[i] {
				if !level_factor_calculated {
					level_factor_calculated = true
					if i > 0 {
						w.level_factors[i] = level_factor_for(haystack[i], haystack[i-1], orig_haystack[i], orig_haystack[i-1], opts)
					}
				}
				w.positions[j] = append(w.positions[j], i)
			}
		}
	}
	w.max_score_per_char = (1.0/float64(len(orig_haystack)) + 1.0/float64(len(needle))) / 2.0
	if !has_atleast_one_match(w) {
		return ans
	}
	var score float64
	for {
		if w.address_is_monotonic() {
			score = w.calc_score()
			if score > ans.Score {
				ans.Score = score
				for i := range ans.Positions {
					ans.Positions[i] = w.position(i)
				}
			}
		}
		if !w.increment_address() {
			break
		}
	}
	if ans.Score > 0 {
		adjust := utils.RuneOffsetsToByteOffsets(item)
		for i := range ans.Positions {
			ans.Positions[i] = adjust(ans.Positions[i])
		}
	}
	return ans
}

func ScoreItems(query string, items []string, opts Options) []*Match {
	ans := make([]*Match, len(items))
	nr := []rune(strings.ToLower(query))
	if opts.Level1 == "" {
		opts.Level1 = LEVEL1
	}
	if opts.Level2 == "" {
		opts.Level2 = LEVEL2
	}
	if opts.Level3 == "" {
		opts.Level3 = LEVEL3
	}
	ropts := resolved_options_type{
		level1: []rune(opts.Level1), level2: []rune(opts.Level2), level3: []rune(opts.Level3),
	}
	utils.Run_in_parallel_over_range(opts.NumberOfThreads, func(start, limit int) error {
		w := workspace_type{}
		for i := start; i < limit; i++ {
			ans[i] = score_item(items[i], i, nr, &ropts, &w)
		}
		return nil
	}, 0, len(items))
	return ans
}
