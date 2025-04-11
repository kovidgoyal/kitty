package kitty

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

var _ = fmt.Print

//go:embed kitty_tests/GraphemeBreakTest.json
var grapheme_break_test_data []byte

type GraphemeBreakTest struct {
	Data    []string `json:"data"`
	Comment string   `json:"comment"`
}

func LoadGraphemeBreakTests() (ans []GraphemeBreakTest, err error) {
	if err := json.Unmarshal(grapheme_break_test_data, &ans); err != nil {
		return nil, fmt.Errorf("Failed to parse GraphemeBreakTest JSON with error: %s", err)
	}
	return
}
