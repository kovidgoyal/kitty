package choose_files

import (
	"bytes"
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
	"unicode"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/fzf"
	"github.com/kovidgoyal/kitty/tools/utils"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func (c CombinedScore) String() string {
	return fmt.Sprintf("{score: %d length: %d index: %d}", c.Score(), c.Length(), c.Index())
}

type ResultItem struct {
	text      string
	ftype     fs.FileMode
	positions []int // may be nil
	score     CombinedScore
}
type ResultsType []*ResultItem

func (r *ResultItem) SetScoreResult(x fzf.Result) {
	r.positions = x.Positions
	r.score.Set_score(uint16(math.MaxUint16 - uint16(x.Score)))
}

func (r ResultItem) IsMatching() bool {
	return r.score.Score() < uint16(math.MaxUint16)
}

func (r ResultItem) String() string {
	return fmt.Sprintf("{text: %#v, %s, positions: %#v}", r.text, r.score, r.positions)
}

func (r *ResultItem) sorted_positions() []int {
	if len(r.positions) > 1 {
		sort.Ints(r.positions)
	}
	return r.positions
}

type FileSystemScanner struct {
	listeners               []chan bool
	in_progress, keep_going atomic.Bool
	root_dir                string
	mutex                   sync.Mutex
	collection              *ResultCollection
	dir_reader              func(path string) ([]fs.DirEntry, error)
	err                     error
}

func NewFileSystemScanner(root_dir string, notify chan bool) (fss *FileSystemScanner) {
	ans := &FileSystemScanner{root_dir: root_dir, listeners: []chan bool{notify}, collection: NewResultCollection(4096)}
	ans.in_progress.Store(true)
	ans.keep_going.Store(true)
	ans.dir_reader = os.ReadDir
	return ans
}

type Scanner interface {
	Start()
	Cancel()
	AddListener(chan bool)
	Len() int
	Batch(offset *CollectionIndex) []ResultItem
	Finished() bool
	Error() error
}

func (fss *FileSystemScanner) lock()   { fss.mutex.Lock() }
func (fss *FileSystemScanner) unlock() { fss.mutex.Unlock() }

func (fss *FileSystemScanner) Error() error {
	fss.lock()
	defer fss.unlock()
	return fss.err
}

func (fss *FileSystemScanner) Start() {
	go fss.worker()
}

func (fss *FileSystemScanner) Cancel() {
	fss.keep_going.Store(false)
}

func (fss *FileSystemScanner) AddListener(x chan bool) {
	fss.lock()
	defer fss.unlock()
	if !fss.in_progress.Load() {
		close(x)
	} else {
		fss.listeners = append(fss.listeners, x)
	}
}

func (fss *FileSystemScanner) Len() int {
	fss.lock()
	defer fss.unlock()
	return fss.collection.Len()
}

func (fss *FileSystemScanner) Batch(offset *CollectionIndex) []ResultItem {
	fss.lock()
	defer fss.unlock()
	return fss.collection.Batch(offset)
}

func (fss *FileSystemScanner) Finished() bool {
	return !fss.in_progress.Load()
}

type sortable_dir_entry struct {
	name     string
	ftype    fs.FileMode
	sort_key []byte
	buf      [unix.NAME_MAX + 1]byte
}

const SymlinkToDir = 1

// lowercase a string into a pre-existing byte buffer with speedups for ASCII
func as_lower(s string, output []byte) int {
	limit := min(len(s), len(output))
	found_non_ascii := false
	pos := 0
	for i := range limit {
		c := s[i]
		if 'A' <= c && c <= 'Z' {
			c += 'a' - 'A'
			if pos < i {
				copy(output[pos:i], s[pos:i])
			}
			output[i] = c
			pos = i + 1
		} else if c >= utf8.RuneSelf {
			if pos < i {
				copy(output[pos:i], s[pos:i])
			}
			found_non_ascii = true
			pos = i
			break
		}
	}
	if !found_non_ascii {
		if pos < limit {
			copy(output[pos:limit], s[pos:limit])
		}
		return limit
	}
	buf := [4]byte{}
	var n int
	for _, r := range s[pos:] {
		o := output[pos:]
		r = unicode.ToLower(r)
		if len(o) > 3 {
			n = utf8.EncodeRune(o, r)
		} else {
			n = utf8.EncodeRune(buf[:], r)
			n = copy(o, buf[:n])
		}
		pos += n
		if pos >= len(output) {
			break
		}
	}
	return pos
}

func (fss *FileSystemScanner) worker() {
	defer func() {
		fss.lock()
		defer fss.unlock()
		fss.in_progress.Store(false)
		if r := recover(); r != nil {
			st, qerr := utils.Format_stacktrace_on_panic(r)
			fss.err = fmt.Errorf("%w\n%s", qerr, st)
		}
		for _, l := range fss.listeners {
			close(l)
		}
	}()
	root_dir, _ := filepath.Abs(fss.root_dir)
	if !strings.HasSuffix(root_dir, string(os.PathSeparator)) {
		root_dir += string(os.PathSeparator)
	}
	dir := root_dir
	base := ""
	pos := &CollectionIndex{}
	var arena []sortable_dir_entry
	var sortable []*sortable_dir_entry
	var idx uint32
	// do a breadth first traversal of the filesystem
	is_root := true
	for dir != "" {
		if !fss.keep_going.Load() {
			break
		}
		entries, err := fss.dir_reader(dir)
		if err != nil {
			if is_root {
				fss.keep_going.Store(false)
				fss.lock()
				fss.err = err
				fss.unlock()
			}
			entries = nil
		}
		if cap(arena) < len(entries) {
			arena = make([]sortable_dir_entry, 0, max(1024, len(entries), 2*cap(arena)))
			sortable = make([]*sortable_dir_entry, 0, cap(arena))
		}
		arena = arena[:len(entries)]
		sortable = sortable[:len(entries)]
		for i, e := range entries {
			arena[i].name = e.Name()
			ftype := e.Type()
			if ftype&fs.ModeSymlink != 0 {
				if st, serr := os.Stat(dir + arena[i].name); serr == nil && st.IsDir() {
					ftype |= SymlinkToDir
				}
			}
			arena[i].ftype = ftype
			if ftype&fs.ModeDir != 0 {
				arena[i].buf[0] = '0'
			} else {
				arena[i].buf[0] = '1'
			}
			n := as_lower(arena[i].name, arena[i].buf[1:])
			arena[i].sort_key = arena[i].buf[:1+n]
			sortable[i] = &arena[i]
		}
		slices.SortFunc(sortable, func(a, b *sortable_dir_entry) int { return bytes.Compare(a.sort_key, b.sort_key) })
		fss.lock()
		for _, e := range sortable {
			i := fss.collection.NextAppendPointer()
			i.ftype = e.ftype
			i.text = base + e.name
			i.score.Set_index(idx)
			idx++
		}
		listeners := fss.listeners
		fss.unlock()
		for _, l := range listeners {
			select {
			case l <- true:
			default:
			}
		}
		if relpath := fss.collection.NextDir(pos); relpath != "" {
			base = relpath + string(os.PathSeparator)
			dir = root_dir + base
		} else {
			dir = ""
		}
		is_root = false
	}
}

type FileSystemScorer struct {
	scanner                 Scanner
	keep_going, is_complete atomic.Bool
	root_dir, query         string
	only_dirs               bool
	mutex                   sync.Mutex
	renderable_results      []*ResultItem
	on_results              func(error, bool)
	current_worker_wait     *sync.WaitGroup
	scorer                  *fzf.FuzzyMatcher
}

func NewFileSystemScorer(root_dir, query string, only_dirs bool, on_results func(error, bool)) (ans *FileSystemScorer) {
	return &FileSystemScorer{
		query: query, root_dir: root_dir, only_dirs: only_dirs, on_results: on_results,
		scorer: fzf.NewFuzzyMatcher(fzf.PATH_SCHEME)}
}

func (fss *FileSystemScorer) lock()   { fss.mutex.Lock() }
func (fss *FileSystemScorer) unlock() { fss.mutex.Unlock() }

func (fss *FileSystemScorer) Start() {
	on_results := make(chan bool)
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
	fss.lock()
	fss.query = query
	fss.renderable_results = nil
	fss.unlock()
	fss.Start()
}

func (fss *FileSystemScorer) worker(on_results chan bool, worker_wait *sync.WaitGroup) {
	defer func() {
		fss.is_complete.Store(true)
		defer worker_wait.Done()
		if r := recover(); r != nil {
			if fss.keep_going.Load() {
				st, qerr := utils.Format_stacktrace_on_panic(r)
				fss.on_results(fmt.Errorf("%w\n%s", qerr, st), true)
			}
		} else {
			if fss.keep_going.Load() {
				fss.on_results(fss.scanner.Error(), true)
			}
		}
	}()
	global_min_score, global_max_score := CombinedScore(math.MaxUint64), CombinedScore(0)
	handle_batch := func(results []ResultItem) (err error) {
		if err = fss.scanner.Error(); err != nil {
			return
		}
		var rp []*ResultItem
		if fss.only_dirs {
			rp = make([]*ResultItem, 0, len(results))
			for i, r := range results {
				if r.ftype.IsDir() {
					rp = append(rp, &results[i])
				}
			}
		} else {
			rp = make([]*ResultItem, len(results))
			for i := range len(rp) {
				rp[i] = &results[i]
			}
		}
		if len(rp) > 0 {
			if fss.query != "" {
				scores, err := fss.scorer.Score(utils.Map(func(r *ResultItem) string { return r.text }, rp), fss.query)
				if err != nil {
					return err
				}
				for i, r := range rp {
					r.SetScoreResult(scores[i])
					r.score.Set_length(uint16(len(r.text)))
				}
				rp = utils.Filter(rp, func(r *ResultItem) bool { return r.IsMatching() })
			} else {
				for _, r := range rp {
					r.score &= 0b11111111111111111111111111111111 // only preserve index
					r.positions = nil
				}
			}
		}
		min_score, max_score := CombinedScore(math.MaxUint64), CombinedScore(0)
		if len(rp) > 0 {
			slices.SortFunc(rp, func(a, b *ResultItem) int { return cmp.Compare(a.score, b.score) })
			min_score, max_score = rp[0].score, rp[len(rp)-1].score
		}
		var rr []*ResultItem
		fss.lock()
		existing := fss.renderable_results
		fss.unlock()
		switch {
		case min_score >= global_max_score:
			rr = append(existing, rp...)
		case max_score < global_min_score:
			rr = make([]*ResultItem, len(existing)+len(rp), max(16*1024, len(existing)+len(rp), 2*cap(existing)))
			copy(rr, rp)
			copy(rr[len(rp):], existing)
		default:
			rr = merge_sorted_slices(existing, rp)
		}
		global_min_score = min(global_min_score, min_score)
		global_max_score = max(global_max_score, max_score)
		fss.lock()
		fss.renderable_results = rr
		fss.unlock()
		return
	}

	offset := &CollectionIndex{}
	for range on_results {
		if !fss.keep_going.Load() {
			break
		}
		results := fss.scanner.Batch(offset)
		if len(results) > 0 || fss.scanner.Error() != nil {
			fss.on_results(handle_batch(results), false)
		}
	}
	for fss.keep_going.Load() {
		b := fss.scanner.Batch(offset)
		if len(b) == 0 {
			break
		}
		fss.on_results(handle_batch(b), false)
	}
}

func (fss *FileSystemScorer) Results() (ans ResultsType, is_finished bool) {
	fss.lock()
	defer fss.unlock()
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

func (m *ResultManager) on_results(err error, is_finished bool) {
	if err != nil {
		m.report_errors <- err
		m.WakeupMainThread()
		return
	}
	m.mutex.Lock()
	defer m.mutex.Unlock()
	if is_finished || time.Since(m.last_wakeup_at) > time.Millisecond*50 {
		m.WakeupMainThread()
		m.last_wakeup_at = time.Now()
	}
}

func merge_sorted_slices(a, b []*ResultItem) []*ResultItem {
	result := make([]*ResultItem, 0, 2*(len(a)+len(b)))
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

func (h *Handler) get_results() (ans ResultsType, is_complete bool) {
	if h.result_manager.scorer == nil {
		return
	}
	return h.result_manager.scorer.Results()
}
