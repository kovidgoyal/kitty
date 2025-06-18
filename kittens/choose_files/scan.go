package choose_files

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode"
	"unsafe"

	"github.com/kovidgoyal/kitty/tools/fzf"
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

type Settings interface {
	OnlyDirs() bool
	ScorePatterns() []ScorePattern
	CurrentDir() string
	SearchText() string
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

	mutex    sync.Mutex
	scorer   *fzf.FuzzyMatcher
	settings Settings

	WakeupMainThread func() bool
}

func NewResultManager(err_chan chan error, settings Settings, WakeupMainThread func() bool) *ResultManager {
	ans := &ResultManager{
		scan_requests:    make(chan ScanRequest, 256),
		scan_results:     make(chan ScanResult, 256),
		score_queries:    make(chan ScoreRequest, 256),
		score_results:    make(chan ScoreResult, 256),
		report_errors:    err_chan,
		scorer:           fzf.NewFuzzyMatcher(fzf.PATH_SCHEME),
		settings:         settings,
		WakeupMainThread: WakeupMainThread,
	}
	go ans.scan_worker()
	go ans.scan_result_handler()
	go ans.score_worker()
	go ans.sort_worker()
	return ans
}

func (m *ResultManager) lock() {
	m.mutex.Lock()
}

func (m *ResultManager) unlock() {
	m.mutex.Unlock()
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
		return ResultItem{abspath: filepath.Join(dir, x.Name()), ftype: x.Type()}
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
		st := time.Now()
		if err := m.scan(r.root_dir, r.root_dir, 0); err == nil {
			m.scan_results <- ScanResult{root_dir: r.root_dir, is_finished: true}
		}
		debugprintln(111111111, time.Now().Sub(st), len(m.results_for_current_root_dir))
	}
}

func (m *ResultManager) create_score_query(items []ResultItem, is_finished bool) ScoreRequest {
	return ScoreRequest{root_dir: m.current_root_dir, query: m.current_query, items: utils.Map(
		func(r ResultItem) ResultItem {
			text, err := filepath.Rel(m.current_root_dir, r.abspath)
			if err != nil {
				text = r.abspath
			}
			return ResultItem{abspath: r.abspath, text: text, ltext: strings.ToLower(text), ftype: r.ftype}
		}, items), is_last_for_current_root_dir: is_finished}
}

func (m *ResultManager) scan_result_handler() {
	one := func(r ScanResult) {
		if !m.is_root_dir_current(r.root_dir) {
			return
		}
		var sqr ScoreRequest
		has_items := len(r.items) > 0
		m.lock()
		if has_items {
			m.results_for_current_root_dir = append(m.results_for_current_root_dir, r.items...)
		}
		sqr = m.create_score_query(r.items, r.is_finished)
		if r.is_finished {
			m.current_root_dir_scan_complete = true
		}
		m.unlock()
		m.score_queries <- sqr
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
	m.lock()
	only_dirs := m.settings.OnlyDirs()
	sp := m.settings.ScorePatterns()
	m.unlock()
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
			items[i].score = get_modified_score(items[i].abspath, float64(x.Score), sp)
		}
		items = utils.Filter(items, func(r ResultItem) bool { return r.score > 0 })
	}
	m.score_results <- res
	return
}

func int_cmp(a, b int) int {
	if a < b {
		return -1
	}
	if a > b {
		return 1
	}
	return 0
}

func str_cmp(a, b string) int {
	if a < b {
		return -1
	}
	if a > b {
		return 1
	}
	return 0
}

func float_cmp(a, b float64) int { // deliberately doesnt handle NaN
	if a < b {
		return -1
	}
	if a > b {
		return 1
	}
	return 0
}

func bool_as_int(b bool) int {
	return *(*int)(unsafe.Pointer(&b))
}

func bool_cmp(a, b bool) int {
	return bool_as_int(a) - bool_as_int(b)
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

func cmp_with_score(a, b ResultItem) (ans int) {
	ans = float_cmp(b.score, a.score)
	if ans == 0 {
		ans = int_cmp(len(a.text), len(b.text))
		if ans == 0 {
			ans = int_cmp(count_uppercase(a.text), count_uppercase(b.text))
		}
	}
	return
}

func cmp_without_score(a, b ResultItem) (ans int) {
	ans = bool_cmp(a.ftype.IsDir(), b.ftype.IsDir())
	if ans == 0 {
		ans = str_cmp(a.ltext, b.ltext)
		if ans == 0 {
			ans = int_cmp(count_uppercase(a.text), count_uppercase(b.text))
		}
	}
	return
}

func merge_sorted_slices(a, b []ResultItem, cmp func(a, b ResultItem) int) []ResultItem {
	result := make([]ResultItem, 0, len(a)+len(b))
	i, j := 0, 0
	for i < len(a) && j < len(b) {
		if cmp(a[i], b[j]) <= 0 {
			result = append(result, a[i])
			i++
		} else {
			result = append(result, b[j])
			j++
		}
	}
	result = append(result, a[i:]...)
	return append(result, b[j:]...)
}

func (m *ResultManager) add_score_results(r ScoreResult) (err error) {
	cmp := utils.IfElse(r.query == "", cmp_without_score, cmp_with_score)
	slices.SortStableFunc(r.items, cmp)
	m.lock()
	defer func() {
		m.unlock()
		if r := recover(); r != nil {
			st, qerr := utils.Format_stacktrace_on_panic(r)
			err = fmt.Errorf("%w\n%s", qerr, st)
		}
	}()
	m.renderable_results = merge_sorted_slices(m.renderable_results, r.items, cmp)
	if r.is_last_for_current_root_dir {
		m.current_query_scoring_complete = true
	}
	return
}

func (m *ResultManager) sort_worker() {
	last_wakeup_at := time.Now()
	for r := range m.score_results {
		if m.is_query_current(r.query, r.root_dir) {
			if err := m.add_score_results(r); err != nil {
				m.report_errors <- err
			} else {
				m.lock()
				is_complete := m.current_root_dir_scan_complete && m.current_query_scoring_complete
				m.unlock()
				if is_complete || time.Now().Sub(last_wakeup_at) > time.Millisecond*50 {
					m.WakeupMainThread()
					last_wakeup_at = time.Now()
				}
			}
		}
	}
}

func (m *ResultManager) is_root_dir_current(root_dir string) bool {
	m.lock()
	defer m.unlock()
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
	m.lock()
	defer m.unlock()
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
	m.lock()
	defer m.unlock()
	return root_dir == m.current_root_dir && query == m.current_query
}

func (m *ResultManager) set_query(query string) {
	var sqr *ScoreRequest
	m.lock()
	defer func() {
		m.unlock()
		if sqr != nil {
			m.score_queries <- *sqr
		}
	}()
	if query == m.current_query {
		return
	}
	m.current_query = query
	m.matches_for_current_query = nil
	m.renderable_results = nil
	m.current_query_scoring_complete = false
	if m.results_for_current_root_dir != nil {
		s := m.create_score_query(m.results_for_current_root_dir, m.current_root_dir_scan_complete)
		sqr = &s
	} else if m.current_root_dir_scan_complete {
		m.current_query_scoring_complete = true
	}
}

func (h *Handler) get_results() (ans []ResultItem, in_progress bool) {
	h.result_manager.lock()
	defer h.result_manager.unlock()
	ans = h.result_manager.renderable_results
	in_progress = !h.result_manager.current_query_scoring_complete || !h.result_manager.current_root_dir_scan_complete
	return
}
