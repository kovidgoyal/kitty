// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package hints

import (
	"math"
	"strings"
	"testing"

	"github.com/kovidgoyal/kitty"
)

func TestPrefixFreeHints(t *testing.T) {
	// Test hints_to_skip
	testsToSkip := []struct {
		n, alphabetSize, expected int
	}{
		{5, 3, 1},
		{6, 3, 2},
		{4, 3, 1},
		{3, 3, 0},
		{2, 3, 0},
		{1, 3, 0},
		{0, 3, 0},
	}
	for _, tc := range testsToSkip {
		actual := hints_to_skip(tc.n, tc.alphabetSize)
		if actual != tc.expected {
			t.Errorf("hints_to_skip(%d, %d) = %d, expected %d", tc.n, tc.alphabetSize, actual, tc.expected)
		}
	}

	// Test prefix-free property verification
	alphabets := []string{"abc", "0123456789"}
	for _, alph := range alphabets {
		l := len(alph)
		for n := 1; n <= 10; n++ {
			total_hints := int(math.Pow(float64(2), float64(n)))
			skip := hints_to_skip(total_hints, l)
			hints := make([]string, total_hints)
			for i := 0; i < total_hints; i++ {
				hints[i] = generate_prefix_free_hint(skip+1+i, alph)
			}
			// Verify that no hint is a prefix of another hint
			for i := 0; i < total_hints; i++ {
				for j := 0; j < total_hints; j++ {
					if i == j {
						continue
					}
					if strings.HasPrefix(hints[j], hints[i]) {
						t.Errorf("For alphabet %q and n=%d: %q is a prefix of %q (skip=%d)", alph, total_hints, hints[i], hints[j], skip)
					}
				}
			}
		}
	}

	// HintsOffset + PrefixFree Test case 1: HintsOffset is smaller than dynamic
	// offset (dynamic offset wins)
	//
	// With 4 matches, and alphabet size 3:
	// hints_to_skip(4, 3) = 1.
	// HintsOffset = 0.
	// Effective offset = max(0, 1) = 1.
	// Ascending = true.
	// Match 0: 0 + 1 + 1 = 2 -> "b"
	// Match 1: 1 + 1 + 1 = 3 -> "c"
	// Match 2: 2 + 1 + 1 = 4 -> "aa"
	// Match 3: 3 + 1 + 1 = 5 -> "ab"
	opts1 := &Options{
		Type:        "url",
		UrlPrefixes: "default",
		Regex:       kitty.HintsDefaultRegex,
		PrefixFree:  true,
		Alphabet:    "abc",
		HintsOffset: 0,
		Ascending:   false, // default
	}
	_, marks1, _, err := find_marks("http://a.com http://b.com http://c.com http://d.com", opts1)
	if err != nil {
		t.Fatalf("find_marks failed: %v", err)
	}
	expectedCodes1 := []string{"ab", "aa", "c", "b"}
	for i, m := range marks1 {
		hint := generate_prefix_free_hint(m.Index, opts1.Alphabet)
		if hint != expectedCodes1[i] {
			t.Errorf("Case 1 - Match %d: got hint %q, expected %q", i, hint, expectedCodes1[i])
		}
	}

	// HintsOffset + PrefixFree Test case 2: HintsOffset is larger than dynamic
	// offset (HintsOffset wins)
	//
	// With 4 matches, and alphabet size 3:
	// hints_to_skip(4, 3) = 1.
	// HintsOffset = 3.
	// Effective offset = max(3, 1) = 3.
	// Ascending = true.
	// Match 0: 0 + 3 + 1 = 4 -> "aa"
	// Match 1: 1 + 3 + 1 = 5 -> "ab"
	// Match 2: 2 + 3 + 1 = 6 -> "ac"
	// Match 3: 3 + 3 + 1 = 7 -> "ba"
	opts2 := &Options{
		Type:        "url",
		UrlPrefixes: "default",
		Regex:       kitty.HintsDefaultRegex,
		PrefixFree:  true,
		Alphabet:    "abc",
		HintsOffset: 3,
		Ascending:   true,
	}
	_, marks2, _, err := find_marks("http://a.com http://b.com http://c.com http://d.com", opts2)
	if err != nil {
		t.Fatalf("find_marks failed: %v", err)
	}
	expectedCodes2 := []string{"aa", "ab", "ac", "ba"}
	for i, m := range marks2 {
		hint := generate_prefix_free_hint(m.Index, opts2.Alphabet)
		if hint != expectedCodes2[i] {
			t.Errorf("Case 2 - Match %d: got hint %q, expected %q", i, hint, expectedCodes2[i])
		}
	}
}
