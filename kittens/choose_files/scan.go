package choose_files

import (
	"cmp"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/tui/subseq"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type ResultItem struct {
	text, abspath string
	dir_entry     os.DirEntry
	positions     []int // may be nil
}

func (r ResultItem) String() string {
	return fmt.Sprintf("{text: %#v, abspath: %#v, is_dir: %v, positions: %#v}", r.text, r.abspath, r.dir_entry.IsDir(), r.positions)
}

type dir_cache map[string][]ResultItem

type ScanCache struct {
	dir_entries           dir_cache
	mutex                 sync.Mutex
	root_dir, search_text string
	in_progress           bool
	matches               []*ResultItem
}

func (sc *ScanCache) get_cached_entries(root_dir string) (ans []ResultItem, found bool) {
	sc.mutex.Lock()
	defer sc.mutex.Unlock()
	ans, found = sc.dir_entries[root_dir]
	return
}

func (sc *ScanCache) set_cached_entries(root_dir string, e []ResultItem) {
	sc.mutex.Lock()
	defer sc.mutex.Unlock()
	sc.dir_entries[root_dir] = e
}

func scan_dir(path, root_dir string) []ResultItem {
	if ans, err := os.ReadDir(path); err == nil {
		if rel, err := filepath.Rel(root_dir, path); err == nil {
			return utils.Map(func(x os.DirEntry) ResultItem {
				path := filepath.Join(path, x.Name())
				r := filepath.Join(rel, x.Name())
				if root_dir == "/" {
					r = "/" + r
				}
				return ResultItem{dir_entry: x, abspath: path, text: r}
			}, ans)
		}
	}
	return []ResultItem{}
}

func is_excluded(path string, exclude_patterns []*regexp.Regexp) bool {
	for _, pattern := range exclude_patterns {
		if pattern.MatchString(path) {
			return true
		}
	}
	return false
}

func (sc *ScanCache) fs_scan(root_dir, current_dir string, max_depth int, exclude_patterns []*regexp.Regexp, seen map[string]bool) (ans []ResultItem) {
	var found bool
	if ans, found = sc.get_cached_entries(current_dir); !found {
		ans = scan_dir(current_dir, root_dir)
		sc.set_cached_entries(current_dir, ans)
	}
	ans = slices.Clone(ans)
	// now recurse into directories
	if max_depth > 0 {
		for _, x := range ans {
			if x.dir_entry.IsDir() && !seen[x.abspath] && !is_excluded(x.abspath, exclude_patterns) {
				seen[x.abspath] = true
				ans = append(ans, sc.fs_scan(root_dir, x.abspath, max_depth-1, exclude_patterns, seen)...)
			}
		}
	}
	return
}

func sort_items_without_search_text(items []ResultItem) (ans []*ResultItem) {
	type s struct {
		ltext          string
		num_of_slashes int
		is_dir         bool
		is_hidden      bool
		r              *ResultItem
	}
	hidden_pat := regexp.MustCompile(`(^|/)\.[^/]+(/|$)`)
	d := utils.Map(func(x ResultItem) s {
		return s{strings.ToLower(x.text), strings.Count(x.text, "/"), x.dir_entry.IsDir(), hidden_pat.MatchString(x.abspath), &x}
	}, items)
	sort.Slice(d, func(i, j int) bool {
		a, b := d[i], d[j]
		if a.num_of_slashes == b.num_of_slashes {
			if a.is_dir == b.is_dir {
				if a.is_hidden == b.is_hidden {
					return a.ltext < b.ltext
				}
				return b.is_hidden
			}
			return a.is_dir
		}
		return a.num_of_slashes < b.num_of_slashes
	})
	return utils.Map(func(s s) *ResultItem { return s.r }, d)
}

func get_modified_score(r *ResultItem, score float64, score_patterns []ScorePattern) float64 {
	for _, sp := range score_patterns {
		if sp.pat.MatchString(r.abspath) {
			score = sp.op(score, sp.val)
		}
	}
	return score
}

func (sc *ScanCache) scan(root_dir, search_text string, max_depth int, exclude_patterns []*regexp.Regexp, score_patterns []ScorePattern) (ans []*ResultItem) {
	seen := make(map[string]bool, 1024)
	matches := sc.fs_scan(root_dir, root_dir, max_depth, exclude_patterns, seen)
	if search_text == "" {
		ans = sort_items_without_search_text(matches)
		return
	}
	pm := make(map[string]*ResultItem, len(ans))
	for _, x := range matches {
		nx := x
		pm[x.text] = &nx
	}
	matches2 := utils.Filter(subseq.ScoreItems(search_text, utils.Keys(pm), subseq.Options{}), func(x *subseq.Match) bool {
		return x.Score > 0
	})
	type s struct {
		r     *ResultItem
		score float64
	}
	ss := utils.Map(func(m *subseq.Match) s {
		x := pm[m.Text]
		x.positions = m.Positions
		return s{x, get_modified_score(x, m.Score, score_patterns)}
	}, matches2)
	slices.SortFunc(ss, func(a, b s) int { return cmp.Compare(b.score, a.score) })
	return utils.Map(func(s s) *ResultItem { return s.r }, ss)
}

func (h *Handler) get_results() (ans []*ResultItem, in_progress bool) {
	sc := &h.scan_cache
	sc.mutex.Lock()
	defer sc.mutex.Unlock()
	if sc.dir_entries == nil {
		sc.dir_entries = make(dir_cache, 512)
	}
	if sc.root_dir == h.state.CurrentDir() && sc.search_text == h.state.SearchText() {
		return sc.matches, sc.in_progress
	}
	sc.in_progress = true
	sc.matches = nil
	root_dir := h.state.CurrentDir()
	search_text := h.state.SearchText()
	sc.root_dir = root_dir
	sc.search_text = search_text
	md, ep, sp := h.state.MaxDepth(), h.state.ExcludePatterns(), h.state.ScorePatterns()
	go func() {
		results := sc.scan(root_dir, search_text, md, ep, sp)
		sc.mutex.Lock()
		defer sc.mutex.Unlock()
		if root_dir == sc.root_dir && search_text == sc.search_text {
			sc.matches = results
			sc.in_progress = false
			h.lp.WakeupMainThread()
		}
	}()
	return sc.matches, sc.in_progress
}
