package wcswidth

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"

	"kitty/tools/utils"
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
	cmd := exec.Command(utils.KittyExe(), "+runpy", `
from kitty.constants import read_kitty_resource
import sys
sys.stdout.buffer.write(read_kitty_resource("GraphemeBreakTest.json", "kitty_tests"))
sys.stdout.flush()
`)
	var output []byte
	var err error
	if output, err = cmd.Output(); err != nil {
		t.Fatalf("Getting GraphemeBreakTest.json failed with error: %s", err)
	}
	tests := []GraphemeBreakTest{}
	if err = json.Unmarshal(output, &tests); err != nil {
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
