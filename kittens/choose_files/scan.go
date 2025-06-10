package choose_files

import (
	"cmp"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strings"
	"sync"
	"unicode"

	"github.com/kovidgoyal/kitty/tools/fzf"
	"github.com/kovidgoyal/kitty/tools/tui/subseq"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type ResultItem struct {
	text, ltext, abspath string
	ftype                fs.FileMode
	positions            []int // may be nil
	score                float64
	positions_sorted     bool
}

func (r ResultItem) String() string {
	return fmt.Sprintf("{text: %#v, abspath: %#v, is_dir: %v, positions: %#v}", r.text, r.abspath, r.ftype.IsDir(), r.positions)
}

func (r *ResultItem) sorted_positions() []int {
	if !r.positions_sorted {
		r.positions_sorted = true
		if len(r.positions) > 1 {
			sort.Ints(r.positions)
		}
	}
	return r.positions
}

type ScanRequest struct {
	root_dir string
}

type ScanResult struct {
	root_dir    string
	items       []ResultItem
	err         error
	is_finished bool
}

type ScoreRequest struct {
	root_dir, query              string
	is_last_for_current_root_dir bool
	items                        []ResultItem
}

type ScoreResult struct {
	query, root_dir              string
	is_last_for_current_root_dir bool
	items                        []ResultItem
}

type ResultManager struct {
	current_root_dir               string
	current_root_dir_scan_complete bool
	results_for_current_root_dir   []ResultItem
	scan_requests                  chan ScanRequest
	scan_results                   chan ScanResult

	current_query                  string
	current_query_scoring_complete bool
	matches_for_current_query      []ResultItem
	score_queries                  chan ScoreRequest
	score_results                  chan ScoreResult
	report_errors                  chan error

	renderable_results []ResultItem

	mutex  sync.Mutex
	scorer *fzf.FuzzyMatcher
	state  *State
}

func NewResultManager(err_chan chan error, state *State) *ResultManager {
	ans := &ResultManager{
		scan_requests: make(chan ScanRequest),
		scan_results:  make(chan ScanResult),
		score_queries: make(chan ScoreRequest),
		score_results: make(chan ScoreResult),
		report_errors: err_chan,
		scorer:        fzf.NewFuzzyMatcher(fzf.PATH_SCHEME),
		state:         state,
	}
	go ans.scan_worker()
	go ans.scan_result_handler()
	go ans.score_worker()
	go ans.sort_worker()
	return ans
}

func (m *ResultManager) scan(dir, root_dir string, level int) (err error) {
	defer func() {
		if r := recover(); r != nil {
			st, qerr := utils.Format_stacktrace_on_panic(r)
			err = fmt.Errorf("%w\n%s", qerr, st)
		}
	}()
	items, err := os.ReadDir(dir)
	if err != nil {
		if level == 0 {
			return fmt.Errorf("failed to read directory: %s with error: %w", dir, err)
		}
		return nil
	}
	m.scan_results <- ScanResult{root_dir: root_dir, items: utils.Map(func(x os.DirEntry) ResultItem {
		return ResultItem{abspath: filepath.Join(dir, x.Name())}
	}, items)}
	for _, x := range items {
		if x.IsDir() {
			if !m.is_root_dir_current(root_dir) {
				return
			}
			if err = m.scan(filepath.Join(dir, x.Name()), root_dir, level+1); err != nil {
				return
			}
		}
	}
	return
}

func (m *ResultManager) scan_worker() {
	for r := range m.scan_requests {
		if err := m.scan(r.root_dir, r.root_dir, 0); err == nil {
			m.scan_results <- ScanResult{root_dir: r.root_dir, is_finished: true}
		}
	}
}

func (m *ResultManager) scan_result_handler() {
	one := func(r ScanResult) {
		m.mutex.Lock()
		defer m.mutex.Unlock()
		if !m.is_root_dir_current(r.root_dir) {
			return
		}
		if len(r.items) > 0 {
			m.results_for_current_root_dir = append(m.results_for_current_root_dir, r.items...)
			m.score_queries <- ScoreRequest{root_dir: m.current_root_dir, query: m.current_query, items: utils.Map(
				func(r ResultItem) ResultItem {
					text, err := filepath.Rel(m.current_root_dir, r.abspath)
					if err != nil {
						text = r.abspath
					}
					return ResultItem{abspath: r.abspath, text: text, ltext: strings.ToLower(text), ftype: r.ftype}
				}, r.items), is_last_for_current_root_dir: r.is_finished}
		}
		if r.is_finished {
			m.current_root_dir_scan_complete = true
		}
	}
	for r := range m.scan_results {
		if r.err != nil {
			m.report_errors <- r.err
			continue
		}
		one(r)
	}
}

func (m *ResultManager) score(r ScoreRequest) (err error) {
	items := r.items
	m.mutex.Lock()
	only_dirs := m.state.mode.OnlyDirs()
	m.mutex.Unlock()
	if only_dirs {
		items = utils.Filter(items, func(r ResultItem) bool { return r.ftype.IsDir() })
	}
	res := ScoreResult{query: r.query, items: items, root_dir: r.root_dir, is_last_for_current_root_dir: r.is_last_for_current_root_dir}
	if r.query != "" {
		var r []fzf.Result
		if r, err = m.scorer.ScoreWithCache(utils.Map(func(r ResultItem) string { return r.text }, items), res.query); err != nil {
			return
		}
		for i, x := range r {
			items[i].positions = x.Positions
			items[i].score = float64(x.Score)
		}
	}
	m.score_results <- res
	return
}

func (m *ResultManager) score_worker() {
	for r := range m.score_queries {
		if m.is_query_current(r.query, r.root_dir) {
			if err := m.score(r); err != nil {
				m.report_errors <- err
			}
		}
	}
}

func (m *ResultManager) add_score_results(r ScoreResult) (err error) {
	m.mutex.Lock()
	defer func() {
		m.mutex.Unlock()
		if r := recover(); r != nil {
			st, qerr := utils.Format_stacktrace_on_panic(r)
			err = fmt.Errorf("%w\n%s", qerr, st)
		}
	}()
	_ = make([]ResultItem, 0, len(m.renderable_results)+len(r.items))
	if r.query == "" {
	} else {
	}
	return
}

func (m *ResultManager) sort_worker() {
	for r := range m.score_results {
		if m.is_query_current(r.query, r.root_dir) {
			if err := m.add_score_results(r); err != nil {
				m.report_errors <- err
			}
		}
	}
}

func (m *ResultManager) is_root_dir_current(root_dir string) bool {
	m.mutex.Lock()
	defer m.mutex.Unlock()
	return root_dir == m.current_root_dir
}

func (m *ResultManager) set_root_dir(root_dir string) {
	var err error
	if root_dir == "" || root_dir == "." {
		if root_dir, err = os.Getwd(); err != nil {
			return
		}
	}
	root_dir = utils.Expanduser(root_dir)
	if root_dir, err = filepath.Abs(root_dir); err != nil {
		return
	}
	m.mutex.Lock()
	defer m.mutex.Unlock()
	if m.current_root_dir == root_dir {
		return
	}
	m.current_root_dir = root_dir
	m.results_for_current_root_dir = nil
	m.matches_for_current_query = nil
	m.renderable_results = nil
	m.current_query_scoring_complete = false
	m.current_root_dir_scan_complete = false
	m.scan_requests <- ScanRequest{root_dir: m.current_root_dir}
}

func (m *ResultManager) is_query_current(query, root_dir string) bool {
	m.mutex.Lock()
	defer m.mutex.Unlock()
	return root_dir == m.current_root_dir && query == m.current_query
}

func (m *ResultManager) set_query(query string) {
	m.mutex.Lock()
	defer m.mutex.Unlock()
	if query == m.current_query {
		return
	}
	m.current_query = query
	m.matches_for_current_query = nil
	m.renderable_results = nil
	m.current_query_scoring_complete = false
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
		return s{strings.ToLower(x.text), strings.Count(x.text, "/"), x.ftype.IsDir(), hidden_pat.MatchString(x.abspath), x}
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
					r := &ResultItem{score: score + scores[i].Score, ftype: entries[i].Type(), abspath: child_abspath}
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
