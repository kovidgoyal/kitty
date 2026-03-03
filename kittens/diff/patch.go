// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"bytes"
	"errors"
	"fmt"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
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

type Center struct{ offset, left_size, right_size int }

// HighlightRegion is a highlighted byte region [offset, offset+size) within a line.
type HighlightRegion struct{ offset, size int }

// WordDiffHighlights holds the highlighted regions for one matched pair of changed lines,
// as derived from git --word-diff=porcelain output.
type WordDiffHighlights struct {
	left, right []HighlightRegion
}

type Chunk struct {
	is_context              bool
	left_start, right_start int
	left_count, right_count int
	centers                 []Center
	word_diff               []WordDiffHighlights
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

func changed_center(left, right string) (ans Center) {
	if len(left) > 0 && len(right) > 0 {
		ll, rl := len(left), len(right)
		ml := utils.Min(ll, rl)
		for ; ans.offset < ml && left[ans.offset] == right[ans.offset]; ans.offset++ {
		}
		suffix_count := 0
		for ; suffix_count < ml && left[ll-1-suffix_count] == right[rl-1-suffix_count]; suffix_count++ {
		}
		ans.left_size = ll - suffix_count - ans.offset
		ans.right_size = rl - suffix_count - ans.offset
	}
	return
}

func (self *Chunk) finalize(left_lines, right_lines []string) {
	if !self.is_context && self.left_count == self.right_count {
		for i := 0; i < self.left_count; i++ {
			self.centers = append(self.centers, changed_center(left_lines[self.left_start+i], right_lines[self.right_start+i]))
		}
	}
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

// is_using_git_diff reports whether the current diff command is git.
// It matches both short ("git") and absolute-path forms of the git executable.
func is_using_git_diff() bool {
	return len(diff_cmd) > 0 && GitExe() != "git" &&
		(diff_cmd[0] == GitExe() || filepath.Base(diff_cmd[0]) == "git")
}

// parse_word_diff_section parses one ~-terminated section from git --word-diff=porcelain
// output and returns the highlighted byte regions for the removed (left) and added (right)
// sides of the corresponding line pair.
//
// Each entry in section is a raw word-diff line: the first byte is the marker (' ', '-', '+')
// and the rest is the word content.  Concatenating the contents in order (using context words
// for both sides, removed words only for the left side, added words only for the right side)
// exactly reconstructs the original left/right lines, so byte offsets are computed by
// summing content lengths in the appropriate order.
func parse_word_diff_section(section []string) (left_regions, right_regions []HighlightRegion) {
	left_offset, right_offset := 0, 0
	for _, line := range section {
		if len(line) == 0 {
			continue
		}
		content := line[1:] // strip the leading marker byte
		switch line[0] {
		case ' ':
			left_offset += len(content)
			right_offset += len(content)
		case '-':
			if len(content) > 0 {
				left_regions = append(left_regions, HighlightRegion{left_offset, len(content)})
			}
			left_offset += len(content)
		case '+':
			if len(content) > 0 {
				right_regions = append(right_regions, HighlightRegion{right_offset, len(content)})
			}
			right_offset += len(content)
		}
	}
	return
}

// parse_word_diff_output parses the output of git --word-diff=porcelain and populates
// the word_diff field of each equal-count diff Chunk within patch.
//
// The git word-diff output retains the same @@-hunk headers as a regular unified diff.
// Within each hunk every original line (context or changed) is represented as a
// ~-terminated section.  Context sections contain only ' '-prefixed words; changed
// sections also contain '-' and/or '+' words whose contents form the highlighted regions.
func parse_word_diff_output(raw string, patch *Patch) {
	if len(patch.all_hunks) == 0 {
		return
	}

	hunk_idx := -1
	var current_hunk *Hunk
	left_line := 0

	var current_section []string

	// find_diff_chunk returns the diff Chunk that owns abs_left_line (absolute 0-based),
	// plus the index of that line within the chunk.  Only equal-count chunks qualify.
	find_diff_chunk := func(abs_left_line int) (*Chunk, int) {
		if current_hunk == nil {
			return nil, -1
		}
		for _, chunk := range current_hunk.chunks {
			if !chunk.is_context &&
				chunk.left_start <= abs_left_line &&
				abs_left_line < chunk.left_start+chunk.left_count &&
				chunk.left_count == chunk.right_count {
				return chunk, abs_left_line - chunk.left_start
			}
		}
		return nil, -1
	}

	process_section := func() {
		defer func() { current_section = current_section[:0] }()
		if current_hunk == nil || len(current_section) == 0 {
			left_line++
			return
		}
		// Determine whether this section represents a changed line pair.
		has_diff := false
		for _, l := range current_section {
			if len(l) > 0 && (l[0] == '-' || l[0] == '+') {
				has_diff = true
				break
			}
		}
		if has_diff {
			if chunk, idx := find_diff_chunk(left_line); chunk != nil && idx >= 0 {
				lr, rr := parse_word_diff_section(current_section)
				if len(chunk.word_diff) <= idx {
					chunk.word_diff = append(chunk.word_diff, make([]WordDiffHighlights, idx-len(chunk.word_diff)+1)...)
				}
				chunk.word_diff[idx] = WordDiffHighlights{left: lr, right: rr}
			}
		}
		left_line++
	}

	splitlines_like_git(raw, true, func(line string) {
		if strings.HasPrefix(line, "@@ ") {
			process_section()
			hunk_idx++
			if hunk_idx < len(patch.all_hunks) {
				current_hunk = patch.all_hunks[hunk_idx]
				left_line = current_hunk.left_start
			} else {
				current_hunk = nil
			}
			return
		}
		if line == "~" {
			process_section()
			return
		}
		if len(line) > 0 && (line[0] == ' ' || line[0] == '-' || line[0] == '+') {
			current_section = append(current_section, line)
		}
		// Skip diff/index/---/+++ header lines.
	})
	// Flush any trailing section (file without final newline).
	process_section()
}

// apply_word_diff attempts to run git --word-diff=porcelain and populate the word_diff
// field of each Chunk in patch.  All errors are silently ignored; callers should treat
// word diff as a best-effort enhancement that falls back to the center-based approach.
func apply_word_diff(file1, file2 string, context_count int, patch *Patch) {
	if !is_using_git_diff() || patch == nil || len(patch.all_hunks) == 0 {
		return
	}
	path1, err := filepath.EvalSymlinks(file1)
	if err != nil {
		return
	}
	path2, err := filepath.EvalSymlinks(file2)
	if err != nil {
		return
	}
	cmd := []string{
		GitExe(), "diff", "--no-color", "--no-ext-diff", "--exit-code",
		"-U" + strconv.Itoa(context_count), "--word-diff=porcelain", "--no-index", "--",
		path1, path2,
	}
	c := exec.Command(cmd[0], cmd[1:]...)
	var stdout, stderr bytes.Buffer
	c.Stdout, c.Stderr = &stdout, &stderr
	if err = c.Run(); err != nil {
		var e *exec.ExitError
		if !errors.As(err, &e) || e.ExitCode() != 1 {
			return // unexpected failure; fall back to center-based highlighting
		}
	}
	parse_word_diff_output(stdout.String(), patch)
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
	if err != nil {
		return
	}
	apply_word_diff(file1, file2, context_count, ans) // best-effort; never returns an error
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
