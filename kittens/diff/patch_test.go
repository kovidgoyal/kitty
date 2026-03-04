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
			// common prefix: "the"; common suffix: "brown fox"
			// only "quick" vs "slow" is compared
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
			// common prefix: "foo"; common suffix: "baz"
			// only "bar" vs "qux" compared
			left_regions:  []Region{{4, 3}},
			right_regions: []Region{{4, 3}},
		},
		{
			left: "aaa bbb ccc", right: "aaa xxx yyy ccc",
			// common prefix: "aaa"; common suffix: "ccc"
			// only "bbb" vs "xxx yyy" compared
			left_regions:  []Region{{4, 3}},
			right_regions: []Region{{4, 3}, {8, 3}},
		},
		{
			left: "aaa bbb ccc ddd", right: "aaa ccc ddd",
			// common prefix: "aaa"; common suffix: "ccc ddd"
			// only "bbb" vs "" compared → "bbb" is deleted
			left_regions:  []Region{{4, 3}},
			right_regions: nil,
		},
		{
			// prefix/suffix trimming: "the quick brown" is common prefix,
			// "over the lazy dog" is common suffix; only "fox" vs "cat" differ
			left: "the quick brown fox over the lazy dog", right: "the quick brown cat over the lazy dog",
			left_regions:  []Region{{16, 3}},
			right_regions: []Region{{16, 3}},
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
