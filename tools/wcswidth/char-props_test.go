package wcswidth

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	_ "embed"
	"github.com/google/go-cmp/cmp"

	"kitty"
)

var _ = fmt.Print

type GraphemeBreakTest struct {
	Data    []string `json:"data"`
	Comment string   `json:"comment"`
}

func TestSplitIntoGraphemes(t *testing.T) {
	var m = map[string][]string{
		" \u0308 ": {" \u0308", " "},
		"abc":      {"a", "b", "c"},
	}
	for text, expected := range m {
		if diff := cmp.Diff(expected, SplitIntoGraphemes(text)); diff != "" {
			t.Fatalf("Failed to split %#v into graphemes: %s", text, diff)
		}
	}
	tests := []GraphemeBreakTest{}
	if err := json.Unmarshal(kitty.GraphemeBreakTestData, &tests); err != nil {
		t.Fatalf("Failed to parse GraphemeBreakTest JSON with error: %s", err)
	}
	for i, x := range tests {
		text := strings.Join(x.Data, "")
		actual := SplitIntoGraphemes(text)
		if diff := cmp.Diff(x.Data, actual); diff != "" {
			t.Fatalf("Failed test #%d: split %#v into graphemes (%s): %s", i, text, x.Comment, diff)
		}
	}
}
