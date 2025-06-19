package choose_files

import (
	"cmp"
	"fmt"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/kovidgoyal/kitty/tools/fzf"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type ResultItem struct {
	text, abspath string
	ftype         fs.FileMode
	positions     []int // may be nil
	score         CombinedScore
}

func (r ResultItem) String() string {
	return fmt.Sprintf("{text: %#v, abspath: %#v, is_dir: %v, positions: %#v}", r.text, r.abspath, r.ftype.IsDir(), r.positions)
}

func (r *ResultItem) sorted_positions() []int {
	if len(r.positions) > 1 {
		sort.Ints(r.positions)
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

type Settings interface {
	OnlyDirs() bool
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

func (m *ResultManager) scan(dir, root_dir string, level int, idx *uint32) (err error) {
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
	ritems := utils.Map(func(x os.DirEntry) ResultItem {
		ans := ResultItem{abspath: filepath.Join(dir, x.Name()), text: strings.ToLower(x.Name()), ftype: x.Type()}
		ans.score.Set_index(*idx)
		*idx = *idx + 1
		return ans
	}, items)
	slices.SortFunc(ritems, func(a, b ResultItem) int { return cmp.Compare(a.text, b.text) })
	m.scan_results <- ScanResult{root_dir: root_dir, items: ritems}
	for _, x := range ritems {
		if x.ftype.IsDir() {
			if !m.is_root_dir_current(root_dir) {
				return
			}
			if err = m.scan(x.abspath, root_dir, level+1, idx); err != nil {
				return
			}
		}
	}
	return
}

func (m *ResultManager) scan_worker() {
	for r := range m.scan_requests {
		st := time.Now()
		var idx uint32
		if err := m.scan(r.root_dir, r.root_dir, 0, &idx); err == nil {
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
			return ResultItem{abspath: r.abspath, text: text, ftype: r.ftype}
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

func (r *ResultItem) SetScoreResult(x fzf.Result) {
	r.positions = x.Positions
	r.score.Set_score(uint32(math.MaxUint32 - x.Score))
}

func (m *ResultManager) score(r ScoreRequest) (err error) {
	items := r.items
	only_dirs := m.settings.OnlyDirs()
	if only_dirs {
		items = utils.Filter(items, func(r ResultItem) bool { return r.ftype.IsDir() })
	}
	res := ScoreResult{
		query: r.query, items: items, root_dir: r.root_dir, is_last_for_current_root_dir: r.is_last_for_current_root_dir,
	}
	if r.query != "" {
		var scores []fzf.Result
		if scores, err = m.scorer.ScoreWithCache(utils.Map(func(r ResultItem) string { return r.text }, items), res.query); err != nil {
			return
		}
		matched_items := make([]ResultItem, 0, len(items))
		for i, x := range scores {
			if x.Score > 0 {
				matched_items = append(matched_items, items[i])
				item := &matched_items[len(matched_items)-1]
				item.SetScoreResult(x)
			}
		}
		items = matched_items
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

func merge_sorted_slices(a, b []ResultItem) []ResultItem {
	result := make([]ResultItem, 0, len(a)+len(b))
	i, j := 0, 0
	for i < len(a) && j < len(b) {
		if a[i].score <= b[j].score {
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

type ByRelevance []ResultItem

func (a ByRelevance) Len() int {
	return len(a)
}

func (a ByRelevance) Swap(i, j int) {
	a[i], a[j] = a[j], a[i]
}

func (a ByRelevance) Less(i, j int) bool {
	return a[i].score < a[j].score
}

func (m *ResultManager) add_score_results(r ScoreResult) (err error) {
	min_score, max_score := CombinedScore(math.MaxUint64), CombinedScore(0)
	if len(r.items) > 0 {
		sort.Sort(ByRelevance(r.items))
		min_score = r.items[0].score
		max_score = r.items[len(r.items)-1].score
	}
	_, _ = min_score, max_score
	// renderable_results := merge_sorted_slices(m.renderable_results, r.items)
	renderable_results := append(m.renderable_results, r.items...)
	m.lock()
	defer func() {
		m.unlock()
		if r := recover(); r != nil {
			st, qerr := utils.Format_stacktrace_on_panic(r)
			err = fmt.Errorf("%w\n%s", qerr, st)
		}
	}()
	m.renderable_results = renderable_results
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
