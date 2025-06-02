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
	"unicode"

	"github.com/kovidgoyal/kitty/tools/tui/subseq"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type ResultItem struct {
	text, abspath string
	dir_entry     os.DirEntry
	positions     []int // may be nil
	score         float64
}

func (r ResultItem) String() string {
	return fmt.Sprintf("{text: %#v, abspath: %#v, is_dir: %v, positions: %#v}", r.text, r.abspath, r.dir_entry.IsDir(), r.positions)
}

type dir_cache map[string][]os.DirEntry

type ScanCache struct {
	dir_entries           dir_cache
	mutex                 sync.Mutex
	root_dir, search_text string
	in_progress           bool
	only_dirs             bool
	matches               []*ResultItem
}

func (sc *ScanCache) get_cached_entries(root_dir string) (ans []os.DirEntry, found bool) {
	sc.mutex.Lock()
	defer sc.mutex.Unlock()
	ans, found = sc.dir_entries[root_dir]
	return
}

func (sc *ScanCache) set_cached_entries(root_dir string, e []os.DirEntry) {
	sc.mutex.Lock()
	defer sc.mutex.Unlock()
	sc.dir_entries[root_dir] = e
}

func (sc *ScanCache) readdir(current_dir string) (ans []os.DirEntry) {
	var found bool
	if ans, found = sc.get_cached_entries(current_dir); !found {
		ans, _ = os.ReadDir(current_dir)
		sc.set_cached_entries(current_dir, ans)
	}
	return
}

func sort_items_without_search_text(items []*ResultItem) (ans []*ResultItem) {
	type s struct {
		ltext          string
		num_of_slashes int
		is_dir         bool
		is_hidden      bool
		r              *ResultItem
	}
	hidden_pat := regexp.MustCompile(`(^|/)\.[^/]+(/|$)`)
	d := utils.Map(func(x *ResultItem) s {
		return s{strings.ToLower(x.text), strings.Count(x.text, "/"), x.dir_entry.IsDir(), hidden_pat.MatchString(x.abspath), x}
	}, items)
	sort.SliceStable(d, func(i, j int) bool {
		a, b := d[i], d[j]
		if a.num_of_slashes == b.num_of_slashes {
			if a.is_dir == b.is_dir {
				if a.is_hidden == b.is_hidden {
					if a.ltext == b.ltext {
						return count_uppercase(a.r.text) < count_uppercase(b.r.text)
					}
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

func get_modified_score(abspath string, score float64, score_patterns []ScorePattern) float64 {
	for _, sp := range score_patterns {
		if sp.pat.MatchString(abspath) {
			score = sp.op(score, sp.val)
		}
	}
	return score
}

func count_uppercase(s string) int {
	count := 0
	for _, r := range s {
		if unicode.IsUpper(r) {
			count++
		}
	}
	return count
}

type pos_in_name struct {
	name      string
	positions []int
}

func (r *ResultItem) finalize(positions []pos_in_name) {
	buf := strings.Builder{}
	buf.Grow(256)
	pos := 0
	for i, x := range positions {
		before := buf.Len()
		buf.WriteString(x.name)
		if i != len(positions)-1 {
			buf.WriteRune(os.PathSeparator)
		}
		for _, p := range x.positions {
			r.positions = append(r.positions, p+pos)
		}
		pos += buf.Len() - before
	}
	r.text = buf.String()
	if r.text == "" {
		r.text = string(os.PathSeparator)
	}
}

func (sc *ScanCache) scan_dir(abspath string, patterns []string, positions []pos_in_name, score float64) (ans []*ResultItem) {
	if entries := sc.readdir(abspath); len(entries) > 0 {
		npos := make([]pos_in_name, len(positions)+1)
		copy(npos, positions)
		if sc.only_dirs {
			entries = utils.Filter(entries, func(e os.DirEntry) bool { return e.IsDir() })
		}
		names := make([]string, len(entries))
		for i, e := range entries {
			names[i] = e.Name()
		}
		var scores []*subseq.Match
		pattern := ""
		if len(patterns) > 0 {
			pattern = patterns[0]
		}
		if pattern != "" {
			scores = subseq.ScoreItems(pattern, names, subseq.Options{})
		} else {
			null := subseq.Match{}
			scores = slices.Repeat([]*subseq.Match{&null}, len(names))
		}
		is_last := pattern == "" || len(patterns) <= 1
		for i, n := range names {
			e := entries[i]
			child_abspath := filepath.Join(abspath, n)
			if pattern == "" || scores[i].Score > 0 {
				npos[len(positions)] = pos_in_name{name: n, positions: scores[i].Positions}
				if is_last {
					r := &ResultItem{score: score + scores[i].Score, dir_entry: entries[i], abspath: child_abspath}
					r.finalize(npos)
					ans = append(ans, r)
				} else if e.IsDir() {
					ans = append(ans, sc.scan_dir(child_abspath, patterns[1:], npos, scores[i].Score+score)...)
				}
			}
		}
	}
	return
}

func (sc *ScanCache) scan(root_dir, search_text string, score_patterns []ScorePattern) (ans []*ResultItem) {
	var patterns []string
	switch search_text {
	case "", "/":
	default:
		patterns = strings.Split(filepath.Clean(search_text), string(os.PathSeparator))
	}
	if strings.HasPrefix(search_text, "/") {
		root_dir = "/"
		if len(patterns) > 0 {
			patterns = patterns[1:]
		}
	}
	ans = sc.scan_dir(root_dir, patterns, nil, 0)
	for _, ri := range ans {
		ri.score = get_modified_score(ri.abspath, ri.score, score_patterns)
	}
	has_search_text := search_text != "" && search_text != "/"
	if !has_search_text {
		return sort_items_without_search_text(ans)
	}
	slices.SortStableFunc(ans, func(a, b *ResultItem) int {
		ans := cmp.Compare(b.score, a.score)
		if ans == 0 {
			ans = cmp.Compare(len(a.text), len(b.text))
			if ans == 0 {
				ans = cmp.Compare(count_uppercase(a.text), count_uppercase(b.text))
			}
		}
		return ans
	})
	return
}

func (h *Handler) get_results() (ans []*ResultItem, in_progress bool) {
	sc := &h.scan_cache
	sc.mutex.Lock()
	defer sc.mutex.Unlock()
	if sc.dir_entries == nil {
		sc.dir_entries = make(dir_cache, 512)
	}
	cd := h.state.CurrentDir()
	st := h.state.SearchText()
	only_dirs := h.state.mode.OnlyDirs()
	if st != "" {
		st = filepath.Clean(st)
	}
	if sc.root_dir == cd && sc.search_text == st && sc.only_dirs == only_dirs {
		return sc.matches, sc.in_progress
	}
	sc.in_progress = true
	sc.matches = nil
	sc.root_dir = cd
	sc.search_text = st
	sc.only_dirs = only_dirs
	sp := h.state.ScorePatterns()
	go func() {
		defer h.lp.RecoverFromPanicInGoRoutine()
		results := sc.scan(cd, st, sp)
		sc.mutex.Lock()
		defer sc.mutex.Unlock()
		if cd == sc.root_dir && st == sc.search_text && sc.only_dirs == only_dirs {
			sc.matches = results
			sc.in_progress = false
			h.lp.WakeupMainThread()
		}
	}()
	return sc.matches, sc.in_progress
}
