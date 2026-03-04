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
			left: "the quick brown fox", right: "the slow brown fox",
			// word prefix: "the"; word suffix: "brown fox"
			// pair "quick" vs "slow": no common char prefix/suffix → full words
			left_regions:  []Region{{4, 5}},
			right_regions: []Region{{4, 4}},
		},
		{
			left: "hello world", right: "hello world",
			left_regions:  nil,
			right_regions: nil,
		},
		{
			left: "foo bar baz", right: "foo qux baz",
			// word prefix: "foo"; word suffix: "baz"
			// pair "bar" vs "qux": no common char prefix/suffix → full words
			left_regions:  []Region{{4, 3}},
			right_regions: []Region{{4, 3}},
		},
		{
			left: "aaa bbb ccc", right: "aaa xxx yyy ccc",
			// word prefix: "aaa"; word suffix: "ccc"
			// left changed: ["bbb"], right changed: ["xxx","yyy"]
			// pair ("bbb","xxx"): no common chars → full words; "yyy" is excess
			left_regions:  []Region{{4, 3}},
			right_regions: []Region{{4, 3}, {8, 3}},
		},
		{
			left: "aaa bbb ccc ddd", right: "aaa ccc ddd",
			// word prefix: "aaa"; word suffix: "ccc ddd"
			// left changed: ["bbb"], right changed: [] → pure deletion, full word
			left_regions:  []Region{{4, 3}},
			right_regions: nil,
		},
		{
			// word prefix/suffix trimming first, then char-level trimming on the pair
			left: "the quick brown fox over the lazy dog", right: "the quick brown cat over the lazy dog",
			// pair "fox" vs "cat": no common char prefix/suffix → full words
			left_regions:  []Region{{16, 3}},
			right_regions: []Region{{16, 3}},
		},
		{
			// intra-word char-level trimming: "version1" → "version2"
			// word prefix: none; word suffix: none
			// pair "version1" vs "version2": char prefix="version"(7), suffix=""
			left:          "version1",
			right:         "version2",
			left_regions:  []Region{{7, 1}},
			right_regions: []Region{{7, 1}},
		},
		{
			// intra-word char-level trimming embedded in a sentence
			// word prefix: "update"; word suffix: "done"
			// pair "prefixABsuffix" vs "prefixCDsuffix":
			//   char prefix="prefix"(6), char suffix="suffix"(6)
			//   left highlight: offset=7+6=13, size=2; right same
			left:          "update prefixABsuffix done",
			right:         "update prefixCDsuffix done",
			left_regions:  []Region{{13, 2}},
			right_regions: []Region{{13, 2}},
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
