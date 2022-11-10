/*
Copyright 2012 Google Inc. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package shlex

import (
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var (
	// one two "three four" "five \"six\"" seven#eight # nine # ten
	// eleven 'twelve\'
	testString = "one two \"three four\" \"five \\\"six\\\"\" seven#eight # nine # ten eleven 'twelve\\' thirteen=13 fourteen/14"
)

func TestClassifier(t *testing.T) {
	classifier := newDefaultClassifier()
	tests := map[rune]runeTokenClass{
		' ':  spaceRuneClass,
		'"':  escapingQuoteRuneClass,
		'\'': nonEscapingQuoteRuneClass}
	for runeChar, want := range tests {
		got := classifier.ClassifyRune(runeChar)
		if got != want {
			t.Errorf("ClassifyRune(%v) -> %v. Want: %v", runeChar, got, want)
		}
	}
}

func TestTokenizer(t *testing.T) {
	testInput := testString
	expectedTokens := []*Token{
		{WordToken, "one", 0},
		{SpaceToken, " ", 3},
		{WordToken, "two", 4},
		{SpaceToken, " ", 7},
		{WordToken, "three four", 8},
		{SpaceToken, " ", 20},
		{WordToken, "five \"six\"", 21},
		{SpaceToken, " ", 35},
		{WordToken, "seven#eight", 36},
		{SpaceToken, " ", 47},
		{WordToken, "#", 48},
		{SpaceToken, " ", 49},
		{WordToken, "nine", 50},
		{SpaceToken, " ", 54},
		{WordToken, "#", 55},
		{SpaceToken, " ", 56},
		{WordToken, "ten", 57},
		{SpaceToken, " ", 60},
		{WordToken, "eleven", 61},
		{SpaceToken, " ", 67},
		{WordToken, "twelve\\", 68},
		{SpaceToken, " ", 77},
		{WordToken, "thirteen=13", 78},
		{SpaceToken, " ", 89},
		{WordToken, "fourteen/14", 90},
	}

	tokenizer := NewTokenizer(strings.NewReader(testInput))
	for i, want := range expectedTokens {
		got, err := tokenizer.Next()
		if err != nil {
			t.Error(err)
		}
		if diff := cmp.Diff(want, got); diff != "" {
			t.Fatalf("Tokenizer.Next()[%v] of: %s:\n%s", i, testString, diff)
		}
	}
}

func TestLexer(t *testing.T) {
	testInput := testString
	expectedStrings := []string{"one", "two", "three four", "five \"six\"", "seven#eight", "#", "nine", "#", "ten", "eleven", "twelve\\", "thirteen=13", "fourteen/14"}

	lexer := NewLexer(strings.NewReader(testInput))
	for i, want := range expectedStrings {
		got, err := lexer.Next()
		if err != nil {
			t.Error(err)
		}
		if got != want {
			t.Errorf("Lexer.Next()[%v] of %q -> %v. Want: %v", i, testString, got, want)
		}
	}
}

func TestSplit(t *testing.T) {
	want := []string{"one", "two", "three four", "five \"six\"", "seven#eight", "#", "nine", "#", "ten", "eleven", "twelve\\", "thirteen=13", "fourteen/14"}
	got, err := Split(testString)
	if err != nil {
		t.Error(err)
	}
	if len(want) != len(got) {
		t.Errorf("Split(%q) -> %v. Want: %v", testString, got, want)
	}
	for i := range got {
		if got[i] != want[i] {
			t.Errorf("Split(%q)[%v] -> %v. Want: %v", testString, i, got[i], want[i])
		}
	}
}

func TestSplitForCompletion(t *testing.T) {
	test := func(cmdline string, last_arg_pos int, expected ...string) {
		actual, actual_pos := SplitForCompletion(cmdline)
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed to split: %s\n%s", cmdline, diff)
		}
		if last_arg_pos != actual_pos {
			t.Fatalf("Failed to split: %s\n Last arg pos: %d != %d", cmdline, last_arg_pos, actual_pos)
		}
	}
	test("a b", 2, "a", "b")
	test("a b ", 4, "a", "b", "")
	test("a b  ", 5, "a", "b", "")
	test(`a "b c"`, 2, "a", "b c")
	test(`a "b c`, 2, "a", "b c")
}
