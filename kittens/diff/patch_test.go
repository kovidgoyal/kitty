// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

// eq_hl is a cmp option that allows comparing unexported HighlightRegion fields.
var eq_hl = cmp.AllowUnexported(HighlightRegion{})

func TestParseWordDiffSection(t *testing.T) {
	// Section for "hello world" → "hello earth".
	// " hello " → marker ' ', content "hello " (6 bytes) — context
	// "-world"  → marker '-', content "world"  (5 bytes) — removed at offset 6
	// "+earth"  → marker '+', content "earth"  (5 bytes) — added   at offset 6
	//
	// Left  reconstruction: "hello " + "world" = "hello world" ✓
	// Right reconstruction: "hello " + "earth" = "hello earth" ✓
	section := []string{" hello ", "-world", "+earth"}
	left, right := parse_word_diff_section(section)

	want_left := []HighlightRegion{{6, 5}}
	want_right := []HighlightRegion{{6, 5}}

	if d := cmp.Diff(want_left, left, eq_hl); d != "" {
		t.Errorf("left regions mismatch (-want +got):\n%s", d)
	}
	if d := cmp.Diff(want_right, right, eq_hl); d != "" {
		t.Errorf("right regions mismatch (-want +got):\n%s", d)
	}
}

func TestParseWordDiffSectionMultipleSpans(t *testing.T) {
	// Section for "The quick brown fox" → "The slow brown cat".
	// git tokenises with trailing whitespace included:
	//   " The "   → content "The "   (4 bytes) — context
	//   "-quick " → content "quick " (6 bytes) — removed at offset 4
	//   "+slow "  → content "slow "  (5 bytes) — added   at offset 4
	//   " brown " → content "brown " (6 bytes) — context
	//   "-fox"    → content "fox"    (3 bytes) — removed at offset 4+6+6 = 16 (wait)
	//
	// Offsets:
	//   left:  4 → +6(removed) → 10 → +6(context) → 16 → span{16,3}
	//   right: 4 → +5(added)   →  9 → +6(context) → 15 → span{15,3}
	section := []string{" The ", "-quick ", "+slow ", " brown ", "-fox", "+cat"}
	left, right := parse_word_diff_section(section)

	want_left := []HighlightRegion{{4, 6}, {16, 3}}
	want_right := []HighlightRegion{{4, 5}, {15, 3}}

	if d := cmp.Diff(want_left, left, eq_hl); d != "" {
		t.Errorf("left regions mismatch (-want +got):\n%s", d)
	}
	if d := cmp.Diff(want_right, right, eq_hl); d != "" {
		t.Errorf("right regions mismatch (-want +got):\n%s", d)
	}
}

func TestParseWordDiffSectionContextOnly(t *testing.T) {
	// A context-only section must produce no highlighted regions.
	section := []string{" same line content"}
	left, right := parse_word_diff_section(section)
	if len(left) != 0 || len(right) != 0 {
		t.Errorf("expected no regions for context-only section, got left=%v right=%v", left, right)
	}
}

func TestParseWordDiffOutput(t *testing.T) {
	// Build a minimal Patch: one hunk, one equal-count diff chunk covering lines 0 and 1.
	chunk := &Chunk{
		is_context:  false,
		left_start:  0,
		right_start: 0,
		left_count:  2,
		right_count: 2,
	}
	hunk := &Hunk{
		left_start:  0,
		left_count:  2,
		right_start: 0,
		right_count: 2,
		chunks:      []*Chunk{chunk},
	}
	patch := &Patch{all_hunks: []*Hunk{hunk}}

	// Simulated git --word-diff=porcelain output:
	//   line 0: "hello world" → "hello earth"
	//   line 1: "lazy dog"    → "fat dog"
	raw := "@@ -1,2 +1,2 @@\n" +
		" hello \n" +
		"-world\n" +
		"+earth\n" +
		"~\n" +
		"-lazy \n" +
		"+fat \n" +
		" dog\n" +
		"~\n"

	parse_word_diff_output(raw, patch)

	if len(chunk.word_diff) != 2 {
		t.Fatalf("expected 2 word_diff entries, got %d", len(chunk.word_diff))
	}

	// Line 0: "hello world" → "hello earth"
	//   " hello " content = "hello " (6 bytes) → context
	//   "-world"  content = "world"  (5 bytes) → left  span {6,5}
	//   "+earth"  content = "earth"  (5 bytes) → right span {6,5}
	want_left0 := []HighlightRegion{{6, 5}}
	want_right0 := []HighlightRegion{{6, 5}}

	if d := cmp.Diff(want_left0, chunk.word_diff[0].left, eq_hl); d != "" {
		t.Errorf("line 0 left regions mismatch (-want +got):\n%s", d)
	}
	if d := cmp.Diff(want_right0, chunk.word_diff[0].right, eq_hl); d != "" {
		t.Errorf("line 0 right regions mismatch (-want +got):\n%s", d)
	}

	// Line 1: "lazy dog" → "fat dog"
	//   "-lazy " content = "lazy " (5 bytes) → left  span {0,5}
	//   "+fat "  content = "fat "  (4 bytes) → right span {0,4}
	//   " dog"   content = "dog"   (3 bytes) → context
	want_left1 := []HighlightRegion{{0, 5}}
	want_right1 := []HighlightRegion{{0, 4}}

	if d := cmp.Diff(want_left1, chunk.word_diff[1].left, eq_hl); d != "" {
		t.Errorf("line 1 left regions mismatch (-want +got):\n%s", d)
	}
	if d := cmp.Diff(want_right1, chunk.word_diff[1].right, eq_hl); d != "" {
		t.Errorf("line 1 right regions mismatch (-want +got):\n%s", d)
	}
}

func TestParseWordDiffOutputWithContext(t *testing.T) {
	// Hunk that has a context line before a diff chunk:
	//   line 0: "context line"  (unchanged)
	//   line 1: "hello world"   → "hello earth"
	ctx_chunk := &Chunk{
		is_context:  true,
		left_start:  0,
		right_start: 0,
		left_count:  1,
		right_count: 1,
	}
	diff_chunk := &Chunk{
		is_context:  false,
		left_start:  1,
		right_start: 1,
		left_count:  1,
		right_count: 1,
	}
	hunk := &Hunk{
		left_start:  0,
		left_count:  2,
		right_start: 0,
		right_count: 2,
		chunks:      []*Chunk{ctx_chunk, diff_chunk},
	}
	patch := &Patch{all_hunks: []*Hunk{hunk}}

	raw := "@@ -1,2 +1,2 @@\n" +
		" context line\n" +
		"~\n" +
		" hello \n" +
		"-world\n" +
		"+earth\n" +
		"~\n"

	parse_word_diff_output(raw, patch)

	if len(ctx_chunk.word_diff) != 0 {
		t.Errorf("context chunk should have no word_diff, got %d", len(ctx_chunk.word_diff))
	}
	if len(diff_chunk.word_diff) != 1 {
		t.Fatalf("expected 1 word_diff entry in diff chunk, got %d", len(diff_chunk.word_diff))
	}

	want_left := []HighlightRegion{{6, 5}}
	want_right := []HighlightRegion{{6, 5}}
	if d := cmp.Diff(want_left, diff_chunk.word_diff[0].left, eq_hl); d != "" {
		t.Errorf("left regions mismatch (-want +got):\n%s", d)
	}
	if d := cmp.Diff(want_right, diff_chunk.word_diff[0].right, eq_hl); d != "" {
		t.Errorf("right regions mismatch (-want +got):\n%s", d)
	}
}

func TestParseWordDiffOutputSkipsUnequalChunks(t *testing.T) {
	// A chunk with unequal counts must not receive word_diff data.
	chunk := &Chunk{
		is_context:  false,
		left_start:  0,
		right_start: 0,
		left_count:  2,
		right_count: 1, // unequal
	}
	hunk := &Hunk{
		left_start:  0,
		left_count:  2,
		right_start: 0,
		right_count: 1,
		chunks:      []*Chunk{chunk},
	}
	patch := &Patch{all_hunks: []*Hunk{hunk}}

	raw := "@@ -1,2 +1,1 @@\n" +
		"-removed line one\n" +
		"~\n" +
		"-removed line two\n" +
		"+added line\n" +
		"~\n"

	parse_word_diff_output(raw, patch)

	if len(chunk.word_diff) != 0 {
		t.Errorf("expected no word_diff entries for unequal chunk, got %d", len(chunk.word_diff))
	}
}
