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
	"sync/atomic"
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
type ResultsType []*ResultItem

func (r *ResultItem) SetScoreResult(x fzf.Result) {
	r.positions = x.Positions
	r.score.Set_score(uint32(math.MaxUint32 - x.Score))
}

func (r *ResultItem) Set_relpath(root_dir string) {
	if ans, err := filepath.Rel(root_dir, r.abspath); err == nil {
		r.text = ans
	} else {
		r.text = r.abspath
	}
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

type FileSystemScanner struct {
	listeners               []chan int
	in_progress, keep_going atomic.Bool
	root_dir                string
	mutex                   sync.Mutex
	results                 []ResultItem
	dir_reader              func(path string, level int) ([]fs.DirEntry, error)
	err                     error
}

func NewFileSystemScanner(root_dir string, notify chan int) (fss *FileSystemScanner) {
	ans := &FileSystemScanner{root_dir: root_dir, listeners: []chan int{notify}, results: make([]ResultItem, 0, 1024)}
	ans.in_progress.Store(true)
	ans.keep_going.Store(true)
	ans.dir_reader = func(path string, level int) ([]fs.DirEntry, error) {
		return os.ReadDir(path)
	}
	return ans
}

type Scanner interface {
	Start()
	Cancel()
	AddListener(chan int)
	Len() int
	Batch(offset int) []ResultItem
	Finished() bool
	Error() error
}

func (fss *FileSystemScanner) Error() error {
	fss.mutex.Lock()
	defer fss.mutex.Unlock()
	return fss.err
}

func (fss *FileSystemScanner) Start() {
	go fss.worker()
}

func (fss *FileSystemScanner) Cancel() {
	fss.keep_going.Store(false)
}

func (fss *FileSystemScanner) AddListener(x chan int) {
	fss.mutex.Lock()
	defer fss.mutex.Unlock()
	if !fss.in_progress.Load() {
		close(x)
	} else {
		fss.listeners = append(fss.listeners, x)
	}
}

func (fss *FileSystemScanner) Len() int {
	fss.mutex.Lock()
	defer fss.mutex.Unlock()
	return len(fss.results)
}

func (fss *FileSystemScanner) Batch(offset int) []ResultItem {
	fss.mutex.Lock()
	defer fss.mutex.Unlock()
	if offset >= len(fss.results) {
		return nil
	}
	return fss.results[offset:]
}

func (fss *FileSystemScanner) Finished() bool {
	return !fss.in_progress.Load()
}

func (fss *FileSystemScanner) worker() {
	defer func() {
		fss.mutex.Lock()
		defer fss.mutex.Unlock()
		fss.in_progress.Store(false)
		if r := recover(); r != nil {
			st, qerr := utils.Format_stacktrace_on_panic(r)
			fss.err = fmt.Errorf("%w\n%s", qerr, st)
		}
		for _, l := range fss.listeners {
			close(l)
		}
	}()
	var scan_dir func(string, int)
	seen_dirs := make(map[string]bool)
	scan_dir = func(dir string, level int) {
		if !fss.keep_going.Load() || seen_dirs[dir] {
			return
		}
		seen_dirs[dir] = true
		entries, err := fss.dir_reader(dir, level)
		if err != nil {
			if level == 0 {
				fss.keep_going.Store(false)
				fss.mutex.Lock()
				fss.err = err
				fss.mutex.Unlock()
			}
			return
		}
		ns := fss.results
		new_sz := len(ns) + len(entries)
		if cap(ns) < new_sz {
			ns = make([]ResultItem, len(ns), max(16*1024, new_sz, cap(ns)*2))
			copy(ns, fss.results)
		}
		new_items := ns[len(ns):new_sz]
		for i, x := range entries {
			ftype := x.Type()
			if ftype&fs.ModeSymlink != 0 {
				if st, err := x.Info(); err == nil && st.IsDir() {
					ftype = fs.ModeDir
				}
			}
			new_items[i].ftype = ftype
			new_items[i].abspath = filepath.Join(dir, x.Name())
			new_items[i].text = strings.ToLower(x.Name())
		}
		slices.SortFunc(new_items, func(a, b ResultItem) int {
			if a.ftype&fs.ModeDir == b.ftype&fs.ModeDir {
				return cmp.Compare(a.text, b.text)
			}
			if a.ftype.IsDir() {
				return -1
			}
			return 1
		})
		ns = ns[0:new_sz]
		fss.mutex.Lock()
		fss.results = ns
		listeners := fss.listeners
		num := len(fss.results)
		fss.mutex.Unlock()
		for _, l := range listeners {
			select {
			case l <- num:
			default:
			}
		}
		for _, x := range new_items {
			if x.ftype.IsDir() {
				scan_dir(x.abspath, level+1)
			}
		}
	}
	scan_dir(fss.root_dir, 0)
}

type FileSystemScorer struct {
	scanner                 Scanner
	keep_going, is_complete atomic.Bool
	root_dir, query         string
	only_dirs               bool
	mutex                   sync.Mutex
	renderable_results      []*ResultItem
	on_results              func(error)
	current_worker_wait     *sync.WaitGroup
	scorer                  *fzf.FuzzyMatcher
}

func NewFileSystemScorer(root_dir, query string, only_dirs bool, on_results func(error)) (ans *FileSystemScorer) {
	return &FileSystemScorer{
		query: query, root_dir: root_dir, only_dirs: only_dirs, on_results: on_results,
		scorer: fzf.NewFuzzyMatcher(fzf.PATH_SCHEME)}
}

func (fss *FileSystemScorer) Start() {
	on_results := make(chan int)
	fss.is_complete.Store(false)
	fss.keep_going.Store(true)
	if fss.scanner == nil {
		fss.scanner = NewFileSystemScanner(fss.root_dir, on_results)
		fss.scanner.Start()
	} else {
		fss.scanner.AddListener(on_results)
	}
	fss.current_worker_wait = &sync.WaitGroup{}
	fss.current_worker_wait.Add(1)
	go fss.worker(on_results, fss.current_worker_wait)
}

func (fss *FileSystemScorer) Change_query(query string) {
	if fss.query == query {
		return
	}
	fss.keep_going.Store(false)
	if fss.current_worker_wait != nil {
		fss.current_worker_wait.Wait()
	}
	fss.query = query
	fss.Start()
}

func (fss *FileSystemScorer) worker(on_results chan int, worker_wait *sync.WaitGroup) {
	defer func() {
		fss.is_complete.Store(true)
		defer worker_wait.Done()
		if r := recover(); r != nil {
			if fss.keep_going.Load() {
				st, qerr := utils.Format_stacktrace_on_panic(r)
				fss.on_results(fmt.Errorf("%w\n%s", qerr, st))
			}
		} else {
			if fss.keep_going.Load() {
				fss.on_results(nil)
			}
		}
	}()
	offset := 0
	root_dir := fss.root_dir
	global_min_score, global_max_score := CombinedScore(math.MaxUint64), CombinedScore(0)
	var idx uint32
	handle_batch := func(results []ResultItem) (err error) {
		if err = fss.scanner.Error(); err != nil {
			return
		}
		var rp []*ResultItem
		if fss.only_dirs {
			rp = make([]*ResultItem, 0, len(results))
			for i, r := range results {
				if r.ftype.IsDir() {
					results[i].Set_relpath(root_dir)
					results[i].score.Set_index(idx)
					idx++
					rp = append(rp, &results[i])
				}
			}
		} else {
			rp = make([]*ResultItem, len(results))
			for i := range len(rp) {
				results[i].Set_relpath(root_dir)
				results[i].score.Set_index(idx)
				idx++
				rp[i] = &results[i]
			}
		}
		if fss.query != "" && len(rp) > 0 {
			scores, err := fss.scorer.ScoreWithCache(utils.Map(func(r *ResultItem) string { return r.text }, rp), fss.query)
			if err != nil {
				return err
			}
			for i, r := range rp {
				r.SetScoreResult(scores[i])
			}
		}
		min_score, max_score := CombinedScore(math.MaxUint64), CombinedScore(0)
		if len(rp) > 0 {
			slices.SortFunc(rp, func(a, b *ResultItem) int { return cmp.Compare(a.score, b.score) })
			min_score, max_score = rp[0].score, rp[len(results)-1].score
		}
		var rr []*ResultItem
		fss.mutex.Lock()
		existing := fss.renderable_results
		fss.mutex.Unlock()
		switch {
		case min_score >= global_max_score:
			rr = append(existing, rp...)
		case max_score < global_min_score:
			rr = make([]*ResultItem, len(existing)+len(rp))
			copy(rr, rp)
			copy(rr[len(rp):], existing)
		default:
			rr = merge_sorted_slices(existing, rp)
		}
		fss.mutex.Lock()
		fss.renderable_results = rr
		global_min_score = min(global_min_score, min_score)
		global_max_score = min(global_max_score, max_score)
		fss.mutex.Unlock()
		return
	}
	for range on_results {
		if !fss.keep_going.Load() {
			break
		}
		results := fss.scanner.Batch(offset)
		if len(results) > 0 || fss.scanner.Error() != nil {
			offset += len(results)
			fss.on_results(handle_batch(results))
		}
	}
	if fss.keep_going.Load() {
		fss.on_results(handle_batch(fss.scanner.Batch(offset)))
	}
}

func (fss *FileSystemScorer) Results() (ans ResultsType, is_finished bool) {
	fss.mutex.Lock()
	defer fss.mutex.Unlock()
	return fss.renderable_results, fss.is_complete.Load()
}

func (fss *FileSystemScorer) Cancel() {
	fss.keep_going.Store(false)
	fss.scanner.Cancel()
}

type Settings interface {
	OnlyDirs() bool
	CurrentDir() string
	SearchText() string
}

type ResultManager struct {
	report_errors    chan error
	WakeupMainThread func() bool
	settings         Settings

	scorer         *FileSystemScorer
	mutex          sync.Mutex
	last_wakeup_at time.Time
}

func NewResultManager(err_chan chan error, settings Settings, WakeupMainThread func() bool) *ResultManager {
	ans := &ResultManager{
		report_errors:    err_chan,
		settings:         settings,
		WakeupMainThread: WakeupMainThread,
	}
	return ans
}

func (m *ResultManager) on_results(err error) {
	if err != nil {
		m.report_errors <- err
		m.WakeupMainThread()
		return
	}
	m.mutex.Lock()
	defer m.mutex.Unlock()
	if time.Since(m.last_wakeup_at) > time.Millisecond*50 {
		m.WakeupMainThread()
		m.last_wakeup_at = time.Now()
	}
}

func merge_sorted_slices(a, b []*ResultItem) []*ResultItem {
	result := make([]*ResultItem, 0, len(a)+len(b))
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
	if m.scorer != nil {
		m.scorer.Cancel()
	}
	m.scorer = NewFileSystemScorer(root_dir, "", m.settings.OnlyDirs(), m.on_results)
	m.scorer.Start()
}

func (m *ResultManager) set_query(query string) {
	if m.scorer == nil {
		m.scorer = NewFileSystemScorer(".", "", m.settings.OnlyDirs(), m.on_results)
		m.scorer.Start()
	} else {
		m.scorer.Change_query(query)
	}
}

func (h *Handler) get_results() (ans ResultsType, in_progress bool) {
	if h.result_manager.scorer == nil {
		return
	}
	return h.result_manager.scorer.Results()
}
