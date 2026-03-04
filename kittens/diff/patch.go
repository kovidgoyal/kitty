// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"bytes"
	"errors"
	"fmt"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"

	parallel "github.com/kovidgoyal/go-parallel"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

var _ = fmt.Print

const GIT_DIFF = `git diff --no-color --no-ext-diff --exit-code -U_CONTEXT_ --no-index --`
const DIFF_DIFF = `diff -p -U _CONTEXT_ --`

var diff_cmd []string

var GitExe = sync.OnceValue(func() string {
	return utils.FindExe("git")
})

var DiffExe = sync.OnceValue(func() string {
	return utils.FindExe("diff")
})

func find_differ() {
	if GitExe() != "git" && exec.Command(GitExe(), "--help").Run() == nil {
		diff_cmd, _ = shlex.Split(GIT_DIFF)
	} else if DiffExe() != "diff" && exec.Command(DiffExe(), "--help").Run() == nil {
		diff_cmd, _ = shlex.Split(DIFF_DIFF)
	} else {
		diff_cmd = []string{}
	}
}

func set_diff_command(q string) error {
	switch q {
	case "auto":
		find_differ()
	case "builtin", "":
		diff_cmd = []string{}
	case "diff":
		diff_cmd, _ = shlex.Split(DIFF_DIFF)
	case "git":
		diff_cmd, _ = shlex.Split(GIT_DIFF)
	default:
		c, err := shlex.Split(q)
		if err != nil {
			return err
		}
		diff_cmd = c
	}
	return nil
}

// Region represents a highlighted byte range within a line.
type Region struct{ offset, size int }

// Center holds the highlighted regions for the left (removed) and right (added) sides of a changed line pair.
type Center struct {
	left_regions  []Region
	right_regions []Region
}

type Chunk struct {
	is_context              bool
	left_start, right_start int
	left_count, right_count int
	centers                 []Center
}

func (self *Chunk) add_line() {
	self.right_count++
}

func (self *Chunk) remove_line() {
	self.left_count++
}

func (self *Chunk) context_line() {
	self.left_count++
	self.right_count++
}

// changed_center computes the central changed region of left/right at the byte level.
func changed_center(left, right string) (ans Center) {
	if len(left) > 0 && len(right) > 0 {
		ll, rl := len(left), len(right)
		ml := utils.Min(ll, rl)
		offset := 0
		for ; offset < ml && left[offset] == right[offset]; offset++ {
		}
		suffix_count := 0
		for ; suffix_count < ml && left[ll-1-suffix_count] == right[rl-1-suffix_count]; suffix_count++ {
		}
		left_size := ll - suffix_count - offset
		right_size := rl - suffix_count - offset
		if left_size > 0 {
			ans.left_regions = []Region{{offset: offset, size: left_size}}
		}
		if right_size > 0 {
			ans.right_regions = []Region{{offset: offset, size: right_size}}
		}
	}
	return
}

var word_regexp = sync.OnceValues(func() (*regexp.Regexp, error) {
	pattern := `\S+`
	if conf != nil && conf.Word_regex != "" {
		pattern = conf.Word_regex
	}
	return regexp.Compile(pattern)
})

// word_diff_center computes highlighted regions for changed words between left and right.
func word_diff_center(left, right string, re *regexp.Regexp) Center {
	left_matches := re.FindAllStringIndex(left, -1)
	right_matches := re.FindAllStringIndex(right, -1)

	type word struct {
		text   string
		offset int
		size   int
	}
	left_words := make([]word, len(left_matches))
	right_words := make([]word, len(right_matches))
	for i, m := range left_matches {
		left_words[i] = word{text: left[m[0]:m[1]], offset: m[0], size: m[1] - m[0]}
	}
	for i, m := range right_matches {
		right_words[i] = word{text: right[m[0]:m[1]], offset: m[0], size: m[1] - m[0]}
	}

	// Strip common prefix and suffix words so LCS only runs on the differing middle.
	prefix := 0
	for prefix < len(left_words) && prefix < len(right_words) && left_words[prefix].text == right_words[prefix].text {
		prefix++
	}
	suffix := 0
	for suffix < len(left_words)-prefix && suffix < len(right_words)-prefix &&
		left_words[len(left_words)-1-suffix].text == right_words[len(right_words)-1-suffix].text {
		suffix++
	}
	lw := left_words[prefix : len(left_words)-suffix]
	rw := right_words[prefix : len(right_words)-suffix]

	m, n := len(lw), len(rw)
	// LCS dynamic programming table
	dp := make([][]int, m+1)
	for i := range dp {
		dp[i] = make([]int, n+1)
	}
	for i := 1; i <= m; i++ {
		for j := 1; j <= n; j++ {
			if lw[i-1].text == rw[j-1].text {
				dp[i][j] = dp[i-1][j-1] + 1
			} else if dp[i-1][j] > dp[i][j-1] {
				dp[i][j] = dp[i-1][j]
			} else {
				dp[i][j] = dp[i][j-1]
			}
		}
	}

	// Backtrack to find changed words within the middle slice.
	left_changed := make([]bool, m)
	right_changed := make([]bool, n)
	i, j := m, n
	for i > 0 && j > 0 {
		if lw[i-1].text == rw[j-1].text {
			i--
			j--
		} else if dp[i-1][j] > dp[i][j-1] {
			left_changed[i-1] = true
			i--
		} else {
			right_changed[j-1] = true
			j--
		}
	}
	for i > 0 {
		left_changed[i-1] = true
		i--
	}
	for j > 0 {
		right_changed[j-1] = true
		j--
	}

	// Remap changed flags to absolute indices within the full words arrays.
	left_changed_abs := make([]bool, len(left_words))
	right_changed_abs := make([]bool, len(right_words))
	for k, c := range left_changed {
		left_changed_abs[prefix+k] = c
	}
	for k, c := range right_changed {
		right_changed_abs[prefix+k] = c
	}

	// Verify that every changed word at index i has a corresponding changed
	// word at the same index i on the other side.  If any position is changed
	// on exactly one side, the lines differ in word count and it makes more
	// sense to highlight the single changed central region of the whole line.
	max_idx := max(len(left_words), len(right_words))
	for idx := 0; idx < max_idx; idx++ {
		lc := idx < len(left_words) && left_changed_abs[idx]
		rc := idx < len(right_words) && right_changed_abs[idx]
		if lc != rc {
			return changed_center(left, right)
		}
	}

	// All changed words are positionally paired.  Apply character-level
	// prefix/suffix trimming to each pair so only the differing central bytes
	// are highlighted.
	var ans Center
	for idx := range left_words {
		if !left_changed_abs[idx] {
			continue
		}
		lword := left_words[idx]
		rword := right_words[idx]
		lt := left[lword.offset : lword.offset+lword.size]
		rt := right[rword.offset : rword.offset+rword.size]
		ll, rl := len(lt), len(rt)
		ml := min(ll, rl)
		cpfx := 0
		for cpfx < ml && lt[cpfx] == rt[cpfx] {
			cpfx++
		}
		csfx := 0
		for csfx < ml-cpfx && lt[ll-1-csfx] == rt[rl-1-csfx] {
			csfx++
		}
		lsize := ll - cpfx - csfx
		rsize := rl - cpfx - csfx
		if lsize > 0 {
			ans.left_regions = append(ans.left_regions, Region{offset: lword.offset + cpfx, size: lsize})
		}
		if rsize > 0 {
			ans.right_regions = append(ans.right_regions, Region{offset: rword.offset + cpfx, size: rsize})
		}
	}
	return ans
}

func (self *Chunk) finalize(_ []string, _ []string) {
	// Center computation is performed in parallel by Patch.compute_centers
}

type Hunk struct {
	left_start, left_count     int
	right_start, right_count   int
	title                      string
	added_count, removed_count int
	chunks                     []*Chunk
	current_chunk              *Chunk
	largest_line_number        int
}

func (self *Hunk) new_chunk(is_context bool) *Chunk {
	left_start, right_start := self.left_start, self.right_start
	if len(self.chunks) > 0 {
		c := self.chunks[len(self.chunks)-1]
		left_start = c.left_start + c.left_count
		right_start = c.right_start + c.right_count
	}
	return &Chunk{is_context: is_context, left_start: left_start, right_start: right_start}
}

func (self *Hunk) ensure_diff_chunk() {
	if self.current_chunk == nil || self.current_chunk.is_context {
		if self.current_chunk != nil {
			self.chunks = append(self.chunks, self.current_chunk)
		}
		self.current_chunk = self.new_chunk(false)
	}
}

func (self *Hunk) ensure_context_chunk() {
	if self.current_chunk == nil || !self.current_chunk.is_context {
		if self.current_chunk != nil {
			self.chunks = append(self.chunks, self.current_chunk)
		}
		self.current_chunk = self.new_chunk(true)
	}
}

func (self *Hunk) add_line() {
	self.ensure_diff_chunk()
	self.current_chunk.add_line()
	self.added_count++
}

func (self *Hunk) remove_line() {
	self.ensure_diff_chunk()
	self.current_chunk.remove_line()
	self.removed_count++
}

func (self *Hunk) context_line() {
	self.ensure_context_chunk()
	self.current_chunk.context_line()
}

func (self *Hunk) finalize(left_lines, right_lines []string) error {
	if self.current_chunk != nil {
		self.chunks = append(self.chunks, self.current_chunk)
	}
	// Sanity check
	c := self.chunks[len(self.chunks)-1]
	if c.left_start+c.left_count != self.left_start+self.left_count {
		return fmt.Errorf("Left side line mismatch %d != %d", c.left_start+c.left_count, self.left_start+self.left_count)
	}
	if c.right_start+c.right_count != self.right_start+self.right_count {
		return fmt.Errorf("Right side line mismatch %d != %d", c.right_start+c.right_count, self.right_start+self.right_count)
	}
	for _, c := range self.chunks {
		c.finalize(left_lines, right_lines)
	}
	return nil
}

type Patch struct {
	all_hunks                                       []*Hunk
	largest_line_number, added_count, removed_count int
}

func (self *Patch) Len() int { return len(self.all_hunks) }

func splitlines_like_git(raw string, strip_trailing_lines bool, process_line func(string)) {
	sz := len(raw)
	if strip_trailing_lines {
		for sz > 0 && (raw[sz-1] == '\n' || raw[sz-1] == '\r') {
			sz--
		}
	}
	start := 0
	for i := 0; i < sz; i++ {
		switch raw[i] {
		case '\n':
			process_line(raw[start:i])
			start = i + 1
		case '\r':
			process_line(raw[start:i])
			start = i + 1
			if start < sz && raw[start] == '\n' {
				i++
				start++
			}
		}
	}
	if start < sz {
		process_line(raw[start:sz])
	}
}

func parse_range(x string) (start, count int) {
	s, c, found := strings.Cut(x, ",")
	start, _ = strconv.Atoi(s)
	if start < 0 {
		start = -start
	}
	count = 1
	if found {
		count, _ = strconv.Atoi(c)
	}
	return
}

func parse_hunk_header(line string) *Hunk {
	parts := strings.SplitN(line, "@@", 3)
	linespec := strings.TrimSpace(parts[1])
	title := ""
	if len(parts) == 3 {
		title = strings.TrimSpace(parts[2])
	}
	left, right, _ := strings.Cut(linespec, " ")
	ls, lc := parse_range(left)
	rs, rc := parse_range(right)
	return &Hunk{
		title: title, left_start: ls - 1, left_count: lc, right_start: rs - 1, right_count: rc,
		largest_line_number: utils.Max(ls-1+lc, rs-1+rc),
	}
}

func (self *Patch) compute_centers(left_lines, right_lines []string) error {
	word_mode := conf != nil && conf.Word_diff_mode == Word_diff_mode_words
	var re *regexp.Regexp
	if word_mode {
		var err error
		re, err = word_regexp()
		if err != nil {
			return fmt.Errorf("Failed to compile word_regex %q: %w", conf.Word_regex, err)
		}
	}

	type pair struct {
		chunk *Chunk
		idx   int
	}
	var pairs []pair
	for _, hunk := range self.all_hunks {
		for _, chunk := range hunk.chunks {
			if !chunk.is_context && chunk.left_count == chunk.right_count {
				for i := 0; i < chunk.left_count; i++ {
					pairs = append(pairs, pair{chunk, i})
				}
			}
		}
	}
	if len(pairs) == 0 {
		return nil
	}
	centers := make([]Center, len(pairs))
	if err := parallel.Run_in_parallel_over_range(0, func(start, end int) {
		for i := start; i < end; i++ {
			p := pairs[i]
			left := left_lines[p.chunk.left_start+p.idx]
			right := right_lines[p.chunk.right_start+p.idx]
			if word_mode {
				centers[i] = word_diff_center(left, right, re)
			} else {
				centers[i] = changed_center(left, right)
			}
		}
	}, 0, len(pairs)); err != nil {
		return err
	}
	ci := 0
	for _, hunk := range self.all_hunks {
		for _, chunk := range hunk.chunks {
			if !chunk.is_context && chunk.left_count == chunk.right_count {
				chunk.centers = centers[ci : ci+chunk.left_count]
				ci += chunk.left_count
			}
		}
	}
	return nil
}

func parse_patch(raw string, left_lines, right_lines []string) (ans *Patch, err error) {
	ans = &Patch{all_hunks: make([]*Hunk, 0, 32)}
	var current_hunk *Hunk
	splitlines_like_git(raw, true, func(line string) {
		if strings.HasPrefix(line, "@@ ") {
			current_hunk = parse_hunk_header(line)
			ans.all_hunks = append(ans.all_hunks, current_hunk)
		} else if current_hunk != nil {
			var ch byte
			if len(line) > 0 {
				ch = line[0]
			}
			switch ch {
			case '+':
				current_hunk.add_line()
			case '-':
				current_hunk.remove_line()
			case '\\':
			default:
				current_hunk.context_line()
			}
		}
	})
	for _, h := range ans.all_hunks {
		err = h.finalize(left_lines, right_lines)
		if err != nil {
			return
		}
		ans.added_count += h.added_count
		ans.removed_count += h.removed_count
	}
	if len(ans.all_hunks) > 0 {
		ans.largest_line_number = ans.all_hunks[len(ans.all_hunks)-1].largest_line_number
	}
	err = ans.compute_centers(left_lines, right_lines)
	return
}

func run_diff(file1, file2 string, num_of_context_lines int) (ok, is_different bool, patch string, err error) {
	// we resolve symlinks because git diff does not follow symlinks, while diff
	// does. We want consistent behavior, also for integration with git difftool
	// we always want symlinks to be followed.
	path1, err := filepath.EvalSymlinks(file1)
	if err != nil {
		return
	}
	path2, err := filepath.EvalSymlinks(file2)
	if err != nil {
		return
	}
	if len(diff_cmd) == 0 {
		data1, err := data_for_path(path1)
		if err != nil {
			return false, false, "", err
		}
		data2, err := data_for_path(path2)
		if err != nil {
			return false, false, "", err
		}
		patchb := Diff(path1, data1, path2, data2, num_of_context_lines)
		if patchb == nil {
			return true, false, "", nil
		}
		return true, len(patchb) > 0, utils.UnsafeBytesToString(patchb), nil
	} else {
		context := strconv.Itoa(num_of_context_lines)
		cmd := utils.Map(func(x string) string {
			return strings.ReplaceAll(x, "_CONTEXT_", context)
		}, diff_cmd)

		cmd = append(cmd, path1, path2)
		c := exec.Command(cmd[0], cmd[1:]...)
		stdout, stderr := bytes.Buffer{}, bytes.Buffer{}
		c.Stdout, c.Stderr = &stdout, &stderr
		err = c.Run()
		if err != nil {
			var e *exec.ExitError
			if errors.As(err, &e) && e.ExitCode() == 1 {
				return true, true, stdout.String(), nil
			}
			return false, false, stderr.String(), err
		}
		return true, false, stdout.String(), nil
	}
}

func do_diff(file1, file2 string, context_count int) (ans *Patch, err error) {
	ok, _, raw, err := run_diff(file1, file2, context_count)
	if !ok {
		return nil, fmt.Errorf("Failed to diff %s vs. %s with errors:\n%s", file1, file2, raw)
	}
	if err != nil {
		return
	}
	left_lines, err := lines_for_path(file1)
	if err != nil {
		return
	}
	right_lines, err := lines_for_path(file2)
	if err != nil {
		return
	}
	ans, err = parse_patch(raw, left_lines, right_lines)
	return
}

type diff_job struct{ file1, file2 string }

func diff(jobs []diff_job, context_count int) (ans map[string]*Patch, err error) {
	ans = make(map[string]*Patch)
	ctx := images.Context{}
	type result struct {
		file1, file2 string
		err          error
		patch        *Patch
	}
	results := make(chan result, len(jobs))
	if err := ctx.SafeParallel(0, len(jobs), func(nums <-chan int) {
		for i := range nums {
			job := jobs[i]
			r := result{file1: job.file1, file2: job.file2}
			r.patch, r.err = do_diff(job.file1, job.file2, context_count)
			results <- r
		}
	}); err != nil {
		panic(err)
	}
	close(results)
	for r := range results {
		if r.err != nil {
			return nil, r.err
		}
		ans[r.file1] = r.patch
	}
	return ans, nil
}
