package choose_files

import (
	"bytes"
	"cmp"
	"encoding/binary"
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
	"github.com/kovidgoyal/kitty/tools/ignorefiles"
	"github.com/kovidgoyal/kitty/tools/utils"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func (c CombinedScore) String() string {
	return fmt.Sprintf("{score: %d length: %d index: %d}", c.Score(), c.Length(), c.Index())
}

type ignore_file_with_prefix struct {
	impl   ignorefiles.IgnoreFile
	prefix string
}

func (i *ignore_file_with_prefix) is_ignored(name string, ftype fs.FileMode) (ans bool, was_match bool) {
	ans, linenum, _ := i.impl.IsIgnored(i.prefix+name, ftype)
	was_match = linenum > -1
	return
}

type ResultItem struct {
	text         string
	ftype        fs.FileMode
	positions    []int // may be nil
	score        CombinedScore
	ignore_files []ignore_file_with_prefix
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
	listeners                    []chan bool
	in_progress, keep_going      atomic.Bool
	root_dir                     string
	mutex                        sync.Mutex
	collection                   *ResultCollection
	dir_reader                   func(path string) ([]fs.DirEntry, error)
	file_reader                  func(path string) ([]byte, error)
	filter_func                  func(filename string) bool
	global_gitignore             ignorefiles.IgnoreFile
	global_ignore                ignorefiles.IgnoreFile
	respect_ignores, show_hidden bool
	sort_by_last_modified        bool

	err error
}

func new_filesystem_scanner(root_dir string, notify chan bool, filter_func func(string) bool) (fss *FileSystemScanner) {
	ans := &FileSystemScanner{root_dir: root_dir, listeners: []chan bool{notify}, collection: NewResultCollection(4096)}
	ans.in_progress.Store(true)
	ans.keep_going.Store(true)
	ans.dir_reader = os.ReadDir
	ans.file_reader = os.ReadFile
	ans.filter_func = utils.IfElse(filter_func == nil, accept_all, filter_func)
	ans.global_gitignore = ignorefiles.NewGitignore()
	ans.global_ignore = ignorefiles.NewGitignore()
	ans.respect_ignores = true
	ans.show_hidden = false
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

func accept_all(filename string) bool { return true }

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
	var ignore_files []ignore_file_with_prefix
	base := ""
	pos := &CollectionIndex{}
	var arena []sortable_dir_entry
	var sortable []*sortable_dir_entry
	var ignoreable []*sortable_dir_entry
	var idx uint32
	dot_git := os.Getenv("GIT_DIR")
	if dot_git == "" {
		dot_git = ".git"
	}
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
			ignoreable = make([]*sortable_dir_entry, 0, cap(arena))
		}
		arena = arena[:len(entries)]
		sortable = sortable[:0]
		ignoreable = ignoreable[:0]
		ignore_files_copied := false
		add_ignore_file_from_impl := func(impl ignorefiles.IgnoreFile) {
			// we want ignore_files to be a copy as we dont want to
			// change the underlying array of ignore_files as it is
			// referenced by multiple ResultItems
			if !ignore_files_copied {
				ignore_files_copied = true
				n := make([]ignore_file_with_prefix, len(ignore_files), len(ignore_files)+4)
				copy(n, ignore_files)
				ignore_files = n
			}
			ignore_files = append(ignore_files, ignore_file_with_prefix{impl: impl})
		}
		add_ignore_file := func(name string) {
			if data, rerr := fss.file_reader(dir + name); rerr == nil {
				impl := ignorefiles.NewGitignore()
				if rerr = impl.LoadString(utils.UnsafeBytesToString(data)); rerr == nil && impl.Len() > 0 {
					add_ignore_file_from_impl(impl)
				}
			}
		}
		entry_is_ignored := func(name string, ftype fs.FileMode) (is_ignored bool) {
			for _, ignore_file := range ignore_files {
				if iig, was_match := ignore_file.is_ignored(name, ftype); was_match {
					is_ignored = iig
				}
			}
			return
		}
		has_git_ignore, has_dot_git, has_dot_ignore := false, false, false
		sort_order := 1
		for i, e := range entries {
			name := e.Name()
			ftype := e.Type()
			is_dir := ftype&fs.ModeDir != 0
			if !is_dir {
				switch name {
				case ".ignore":
					has_dot_ignore = true
				case ".gitignore":
					has_git_ignore = true
				}
				if !fss.filter_func(name) {
					continue
				}
			} else {
				if name == dot_git {
					has_dot_git = true
				}
			}
			if !fss.show_hidden && name[0] == '.' {
				continue
			}
			arena[i].name = name
			if ftype&fs.ModeSymlink != 0 {
				if st, serr := os.Stat(dir + arena[i].name); serr == nil && st.IsDir() {
					ftype |= SymlinkToDir
				}
			}
			arena[i].ftype = ftype
			if is_dir {
				arena[i].buf[0] = '0'
			} else {
				arena[i].buf[0] = '1'
			}
			if fss.sort_by_last_modified {
				var ts time.Time
				if info, err := e.Info(); err == nil {
					ts = info.ModTime()
				}
				binary.BigEndian.PutUint64(arena[i].buf[1:], uint64(ts.UnixNano()))
				arena[i].sort_key = arena[i].buf[:1+8]
				sort_order = -1
			} else {
				n := as_lower(arena[i].name, arena[i].buf[1:])
				arena[i].sort_key = arena[i].buf[:1+n]
			}
			sortable = append(sortable, &arena[i])
		}
		if fss.respect_ignores {
			if is_root && fss.global_ignore.Len() > 0 {
				add_ignore_file_from_impl(fss.global_ignore)
			}
			if has_dot_git {
				if fss.global_gitignore.Len() > 0 {
					add_ignore_file_from_impl(fss.global_gitignore)
				}
				add_ignore_file(filepath.Join(dot_git, "info", "exclude"))
				if has_git_ignore {
					add_ignore_file(".gitignore")
				}
			}
			if has_dot_ignore {
				add_ignore_file(".ignore")
			}
		}
		final_entries := sortable
		if len(ignore_files) > 0 {
			for _, e := range sortable {
				if !entry_is_ignored(e.name, e.ftype) {
					ignoreable = append(ignoreable, e)
				}

			}
			final_entries = ignoreable
		}
		slices.SortFunc(final_entries, func(a, b *sortable_dir_entry) int { return sort_order * bytes.Compare(a.sort_key, b.sort_key) })
		fss.lock()
		for _, e := range final_entries {
			i := fss.collection.NextAppendPointer()
			i.ftype = e.ftype
			i.text = base + e.name
			i.score.Set_index(idx)
			i.ignore_files = ignore_files
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
		ignore_files = nil
		if relpath, ignf := fss.collection.NextDir(pos); relpath != "" {
			base = relpath + string(os.PathSeparator)
			dir = root_dir + base
			if len(ignf) != 0 {
				name := filepath.Base(relpath) + string(os.PathSeparator)
				ignore_files = utils.Map(func(ignore_file ignore_file_with_prefix) ignore_file_with_prefix {
					return ignore_file_with_prefix{impl: ignore_file.impl, prefix: ignore_file.prefix + name}
				}, ignf)
			}
		} else {
			dir = ""
		}
		is_root = false
	}
}

type FileSystemScorer struct {
	scanner                         Scanner
	keep_going, is_complete         atomic.Bool
	root_dir, query                 string
	filter                          Filter
	only_dirs                       bool
	mutex                           sync.Mutex
	sorted_results                  *SortedResults
	on_results                      func(error, bool)
	current_worker_wait             *sync.WaitGroup
	scorer                          *fzf.FuzzyMatcher
	dir_reader                      func(path string) ([]fs.DirEntry, error)
	file_reader                     func(path string) ([]byte, error)
	global_gitignore, global_ignore ignorefiles.IgnoreFile
	respect_ignores, show_hidden    bool
	sort_by_last_modified           bool
}

func NewFileSystemScorer(root_dir, query string, filter Filter, only_dirs bool, on_results func(error, bool)) (ans *FileSystemScorer) {
	return &FileSystemScorer{
		query: query, root_dir: root_dir, only_dirs: only_dirs, filter: filter, on_results: on_results,
		scorer: fzf.NewFuzzyMatcher(fzf.PATH_SCHEME), sorted_results: NewSortedResults(), respect_ignores: true,
	}
}

func (fss *FileSystemScorer) lock()   { fss.mutex.Lock() }
func (fss *FileSystemScorer) unlock() { fss.mutex.Unlock() }

func (fss *FileSystemScorer) Start() {
	on_results := make(chan bool)
	fss.is_complete.Store(false)
	fss.keep_going.Store(true)
	if fss.scanner == nil {
		sc := new_filesystem_scanner(fss.root_dir, on_results, fss.filter.Match)
		if fss.dir_reader != nil {
			sc.dir_reader = fss.dir_reader
		}
		if fss.file_reader != nil {
			sc.file_reader = fss.file_reader
		}
		if fss.global_gitignore != nil {
			sc.global_gitignore = fss.global_gitignore
		} else if ignore := ignorefiles.GlobalGitignore(); ignore != nil {
			sc.global_gitignore = ignore
		}
		if fss.global_ignore != nil {
			sc.global_ignore = fss.global_ignore
		}
		sc.show_hidden, sc.respect_ignores = fss.show_hidden, fss.respect_ignores
		sc.sort_by_last_modified = fss.sort_by_last_modified
		fss.scanner = sc
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
		if fss.scanner != nil {
			fss.scanner.Cancel()
		}
		fss.current_worker_wait.Wait()
	}
	fss.lock()
	fss.query = query
	fss.sorted_results.Clear()
	fss.unlock()
	fss.Start()
}

func (fss *FileSystemScorer) change_scanner_setting(callback func()) {
	fss.keep_going.Store(false)
	if fss.current_worker_wait != nil {
		if fss.scanner != nil {
			fss.scanner.Cancel()
		}
		fss.current_worker_wait.Wait()
	}
	fss.lock()
	callback()
	fss.sorted_results.Clear()
	fss.scanner = nil
	fss.unlock()
	fss.Start()

}

func (fss *FileSystemScorer) Change_filter(filter Filter) {
	if !fss.filter.Equal(filter) {
		fss.change_scanner_setting(func() { fss.filter = filter })
	}
}

func (fss *FileSystemScorer) Change_show_hidden(val bool) {
	if fss.show_hidden != val {
		fss.change_scanner_setting(func() { fss.show_hidden = val })
	}
}

func (fss *FileSystemScorer) Change_respect_ignores(val bool) {
	if fss.respect_ignores != val {
		fss.change_scanner_setting(func() { fss.respect_ignores = val })
	}
}

func (fss *FileSystemScorer) Change_sort_by_last_modified(val bool) {
	if fss.sort_by_last_modified != val {
		fss.change_scanner_setting(func() { fss.sort_by_last_modified = val })
	}
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
			if fss.filter.Match == nil {
				rp = make([]*ResultItem, len(results))
				for i := range len(rp) {
					rp[i] = &results[i]
				}
			} else {
				rp = make([]*ResultItem, 0, len(results))
				for i, r := range results {
					if r.ftype.IsDir() || fss.filter.Match(filepath.Base(r.text)) {
						rp = append(rp, &results[i])
					}
				}
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
		if len(rp) > 0 {
			slices.SortFunc(rp, func(a, b *ResultItem) int { return cmp.Compare(a.score, b.score) })
		}
		fss.sorted_results.AddSortedSlice(rp)
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

func (fss *FileSystemScorer) Results() (ans *SortedResults, is_finished bool) {
	fss.lock()
	defer fss.unlock()
	return fss.sorted_results, fss.is_complete.Load()
}

func (fss *FileSystemScorer) Cancel() {
	fss.keep_going.Store(false)
	fss.scanner.Cancel()
}

type Settings interface {
	OnlyDirs() bool
	CurrentDir() string
	SearchText() string
	ShowHidden() bool
	RespectIgnores() bool
	SortByLastModified() bool
	Filter() Filter
	GlobalIgnores() ignorefiles.IgnoreFile
	HighlightStyles() (string, string)
	SyntaxAliases() map[string]string
}

type ResultManager struct {
	report_errors    chan error
	WakeupMainThread func() bool
	settings         Settings

	scorer         *FileSystemScorer
	mutex          sync.Mutex
	last_wakeup_at time.Time

	last_click_anchor *CollectionIndex
}

func NewResultManager(err_chan chan error, settings Settings, WakeupMainThread func() bool) *ResultManager {
	ans := &ResultManager{
		report_errors:    err_chan,
		settings:         settings,
		WakeupMainThread: WakeupMainThread,
	}
	return ans
}

func (m *ResultManager) new_scorer() {
	root_dir := m.current_root_dir()
	query := m.settings.SearchText()
	m.scorer = NewFileSystemScorer(root_dir, query, m.settings.Filter(), m.settings.OnlyDirs(), m.on_results)
	m.scorer.respect_ignores = m.settings.RespectIgnores()
	m.scorer.show_hidden = m.settings.ShowHidden()
	m.scorer.global_ignore = m.settings.GlobalIgnores()
	m.scorer.sort_by_last_modified = m.settings.SortByLastModified()
	m.last_click_anchor = nil
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

func (m *ResultManager) current_root_dir() string {
	var err error
	root_dir := m.settings.CurrentDir()
	if root_dir == "" || root_dir == "." {
		if root_dir, err = os.Getwd(); err != nil {
			return "/"
		}
	}
	root_dir = utils.Expanduser(root_dir)
	if root_dir, err = filepath.Abs(root_dir); err != nil {
		return "/"
	}
	return root_dir
}

func (m *ResultManager) set_root_dir() {
	if m.scorer != nil {
		m.scorer.Cancel()
	}
	_ = os.Chdir(m.current_root_dir()) // this is so the terminal emulator can read the wd for launch --directory=current
	m.new_scorer()
	m.mutex.Lock()
	m.last_wakeup_at = time.Time{}
	m.mutex.Unlock()
	m.scorer.Start()
}

func (m *ResultManager) set_something(callback func()) {
	m.mutex.Lock()
	m.last_wakeup_at = time.Time{}
	m.mutex.Unlock()
	if m.scorer == nil {
		m.new_scorer()
		m.scorer.Start()
	} else {
		m.last_click_anchor = nil
		callback()
	}

}

func (m *ResultManager) set_query() {
	m.set_something(func() { m.scorer.Change_query(m.settings.SearchText()) })
}

func (m *ResultManager) set_filter() {
	m.set_something(func() { m.scorer.Change_filter(m.settings.Filter()) })
}

func (m *ResultManager) set_show_hidden() {
	m.set_something(func() { m.scorer.Change_show_hidden(m.settings.ShowHidden()) })
}

func (m *ResultManager) set_respect_ignores() {
	m.set_something(func() { m.scorer.Change_respect_ignores(m.settings.RespectIgnores()) })
}

func (m *ResultManager) set_sort_by_last_modified() {
	m.set_something(func() { m.scorer.Change_sort_by_last_modified(m.settings.SortByLastModified()) })
}

func (h *Handler) get_results() (ans *SortedResults, is_complete bool) {
	if h.result_manager.scorer == nil {
		return
	}
	return h.result_manager.scorer.Results()
}
