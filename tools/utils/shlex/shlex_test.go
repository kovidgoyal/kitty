package shlex

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

var (
	// one two "three four" "five \"six\"" seven#eight # nine # ten
	// eleven 'twelve\'
	testString = "one two \"three four\" \"five \\\"six\\\"\" seven#eight # nine # ten eleven 'twelve\\' thirteen=13 fourteen/14"
)

func TestLexer(t *testing.T) {
	testInput := testString
	expectedStrings := []string{"one", "two", "three four", "five \"six\"", "seven#eight", "#", "nine", "#", "ten", "eleven", "twelve\\", "thirteen=13", "fourteen/14"}

	lexer := NewLexer(testInput)
	for i, want := range expectedStrings {
		got := lexer.Next()
		if got.Value != want {
			t.Errorf("Lexer.Next()[%v] of %q -> %v. Want: %v", i, testString, got, want)
		}
	}
}

type Tok struct {
	Pos int
	Val string
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

	for _, x := range []string{
		`abc\`, `\`, `'abc`, `'`, `"`, `asd\`,
	} {
		_, err := Split(x)
		if err == nil {
			t.Fatalf("Failed to get an error for: %#v", x)
		}
	}
	s := func(q string) (ans []Tok) {
		l := NewLexer(q)
		for {
			w := l.Next()
			if w.Err != nil {
				t.Fatal(w.Err)
			}
			if w.Value == "" {
				break
			}
			ans = append(ans, Tok{w.Pos, w.Value})
		}
		return
	}
	for q, expected := range map[string][]Tok{
		`"ab"`:          {{0, "ab"}},
		`x "ab"y \m`:    {{0, `x`}, {2, `aby`}, {8, `m`}},
		`x'y"\z'1`:      {{0, `xy"\z1`}},
		`\abc\ d`:       {{0, `abc d`}},
		``:              nil,
		`   `:           nil,
		" \tabc\n\t\r ": {{2, "abc"}},
	} {
		if diff := cmp.Diff(expected, s(q)); diff != "" {
			t.Fatalf("Failed for string: %#v\n%s", q, diff)
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
			t.Fatalf("Failed to split: %#v\n Last arg pos: %d != %d", cmdline, last_arg_pos, actual_pos)
		}
	}
	test("a b", 2, "a", "b")
	test("a b ", 4, "a", "b", "")
	test("a b  ", 5, "a", "b", "")
	test(`a "b c"`, 2, "a", "b c")
	test(`a "b c`, 2, "a", "b c")
}

func TestExpandANSICEscapes(t *testing.T) {
	var m = map[string]string{
		"abc":       "abc",
		`a\ab`:      "a\ab",
		`a\eb`:      "a\x1bb",
		`a\r\nb`:    "a\r\nb",
		`a\c b`:     "a\000b",
		`a\c`:       "a\\c",
		`a\x1bb`:    "a\x1bb",
		`a\x1b`:     "a\x1b",
		`a\x1`:      "a\x01",
		`a\x1\\`:    "a\x01\\",
		`a\x1g`:     "a\x01g",
		`a\z\"`:     "a\\z\"",
		`a\123b`:    "a\123b",
		`a\128b`:    "a\0128b",
		`a\u1234e`:  "a\u1234e",
		`a\U1f1eez`: "a\U0001f1eez",
	}
	for q, expected := range m {
		actual := ExpandANSICEscapes(q)
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Failed to process: %#v\n%s", q, diff)
		}
	}

}
