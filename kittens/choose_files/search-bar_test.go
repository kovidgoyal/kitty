package choose_files

import "testing"

func TestDeleteLastWord(t *testing.T) {
	for _, tc := range []struct {
		text, expected string
	}{
		{"", ""},
		{"one", ""},
		{"one two", "one "},
		{"one two  ", "one "},
		{"one\ttwo", "one\t"},
		{"one\u2003two", "one\u2003"},
		{"one   ", ""},
		{"你好 世界", "你好 "},
	} {
		if actual := delete_last_word(tc.text); actual != tc.expected {
			t.Errorf("delete_last_word(%q): expected %q, got %q", tc.text, tc.expected, actual)
		}
	}
}
