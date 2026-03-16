// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"regexp"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/google/go-cmp/cmp/cmpopts"
)

var region_eq = cmpopts.EquateComparable(Region{})

func TestWordDiffCenter(t *testing.T) {
	re := regexp.MustCompile(`\S+`)
	type tc struct {
		left, right   string
		left_regions  []Region
		right_regions []Region
	}
	tests := []tc{
		{
			// word count equal, single substitution at index 1 → positional pair
			// "quick" vs "slow": no common chars → full words
			left: "the quick brown fox", right: "the slow brown fox",
			left_regions:  []Region{{4, 5}},
			right_regions: []Region{{4, 4}},
		},
		{
			left: "hello world", right: "hello world",
			left_regions:  nil,
			right_regions: nil,
		},
		{
			// word count equal, single substitution at index 1 → positional pair
			// "bar" vs "qux": no common chars → full words
			left: "foo bar baz", right: "foo qux baz",
			left_regions:  []Region{{4, 3}},
			right_regions: []Region{{4, 3}},
		},
		{
			// left has 3 words, right has 4 → word counts differ with unmatched
			// changed words → fall back to changed_center
			// changed_center gives: offset=4 (common "aaa "), suffix="ccc"(4)
			// left_size=3 ("bbb"), right_size=7 ("xxx yyy")
			left: "aaa bbb ccc", right: "aaa xxx yyy ccc",
			left_regions:  []Region{{4, 3}},
			right_regions: []Region{{4, 7}},
		},
		{
			// word on left deleted: unmatched changed word → fall back to changed_center
			// changed_center: prefix="aaa "(4), suffix=" ccc ddd"(8)
			// left_size=3 ("bbb"), right_size=-1 → nil
			left: "aaa bbb ccc ddd", right: "aaa ccc ddd",
			left_regions:  []Region{{4, 3}},
			right_regions: nil,
		},
		{
			// word counts equal, single substitution at index 3 → positional pair
			// "fox" vs "cat": no common chars → full words
			left: "the quick brown fox over the lazy dog", right: "the quick brown cat over the lazy dog",
			left_regions:  []Region{{16, 3}},
			right_regions: []Region{{16, 3}},
		},
		{
			// single word, positional pair with common char prefix "version" (7)
			left:          "version1",
			right:         "version2",
			left_regions:  []Region{{7, 1}},
			right_regions: []Region{{7, 1}},
		},
		{
			// positional pair at index 1, char prefix="prefix"(6), suffix="suffix"(6)
			// word at offset 7 → highlight offset 13, size 2
			left:          "update prefixABsuffix done",
			right:         "update prefixCDsuffix done",
			left_regions:  []Region{{13, 2}},
			right_regions: []Region{{13, 2}},
		},
		{
			// equal word count, multiple positional pairs (all words changed)
			// each pair has no common chars → full-word regions
			left: "aaa bbb ccc", right: "xxx yyy zzz",
			left_regions:  []Region{{0, 3}, {4, 3}, {8, 3}},
			right_regions: []Region{{0, 3}, {4, 3}, {8, 3}},
		},
		{
			// pure insertion on right side → unmatched changed word → fall back to changed_center
			// changed_center finds common prefix "aaa bbb ccc" (11 bytes) and suffix "";
			// left_size=0 (nil), right_size=4 (" ddd" inserted at the end)
			left: "aaa bbb ccc", right: "aaa bbb ccc ddd",
			left_regions:  nil,
			right_regions: []Region{{11, 4}},
		},
	}
	for _, tc := range tests {
		c := word_diff_center(tc.left, tc.right, re)
		if diff := cmp.Diff(tc.left_regions, c.left_regions, region_eq); diff != "" {
			t.Errorf("word_diff_center(%q, %q) left_regions mismatch: %s", tc.left, tc.right, diff)
		}
		if diff := cmp.Diff(tc.right_regions, c.right_regions, region_eq); diff != "" {
			t.Errorf("word_diff_center(%q, %q) right_regions mismatch: %s", tc.left, tc.right, diff)
		}
	}
}

func TestChangedCenter(t *testing.T) {
	type tc struct {
		left, right   string
		left_regions  []Region
		right_regions []Region
	}
	tests := []tc{
		{
			left: "the quick brown fox", right: "the slow brown fox",
			left_regions:  []Region{{4, 5}},
			right_regions: []Region{{4, 4}},
		},
		{
			left: "hello world", right: "hello world",
			left_regions:  nil,
			right_regions: nil,
		},
	}
	for _, tc := range tests {
		c := changed_center(tc.left, tc.right)
		if diff := cmp.Diff(tc.left_regions, c.left_regions, region_eq); diff != "" {
			t.Errorf("changed_center(%q, %q) left_regions mismatch: %s", tc.left, tc.right, diff)
		}
		if diff := cmp.Diff(tc.right_regions, c.right_regions, region_eq); diff != "" {
			t.Errorf("changed_center(%q, %q) right_regions mismatch: %s", tc.left, tc.right, diff)
		}
	}
}
