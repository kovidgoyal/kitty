package cli

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/google/go-cmp/cmp"

	"kitty"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"kitty/tools/utils/style"
	"kitty/tools/wcswidth"
)

var _ = fmt.Print

type test_struct struct {
	description               string
	num                       int
	expected_cursor_positions []int
	actual_cursor_positions   []int
	payload                   string
}

const cursor_position_report = "\x1b[6n"
const reset_line = "\r\x1b[K"

func run_tests(tests []*test_struct) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen)
	if err != nil {
		return err
	}
	buf := strings.Builder{}
	buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToSet())
	for _, t := range tests {
		buf.WriteString(t.payload)
		buf.WriteString(reset_line)
		if buf.Len() > 512*1024 {
			buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToReset())
			buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToSet())
		}
	}
	buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToReset())
	buf.WriteString("\x1b[c")

	print_para := func(text string) {
		sz, _ := lp.ScreenSize()
		for _, line := range style.WrapTextAsLines(text, int(sz.WidthCells), style.WrapOptions{Trim_whitespace: true}) {
			lp.Println(line)
		}
		lp.Println()
	}
	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		print_para("These tests work by sending text to the terminal and then querying it for its cursor position. Every test is thus different strings sent to the terminal along with a list of expected cursor positions after each string. A failure means the actual cursor position was different from the expected one. A failure where the first expected cursor position is correct but subsequent ones are not, means that the complete string was rendered at the correct width but individual graphemes from the string were not.")
		print_para("The individual test descriptions use the character ÷ to indicate a position where a break is expected to occur and the character × to indicate a position where no break should happen. ")
		lp.Printf("Running %d tests, please wait...\n", len(tests))

		lp.QueueWriteString(buf.String())
		return "", err
	}
	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		return ""
	}
	current_test_idx := 0
	lp.OnEscapeCode = func(typ loop.EscapeCodeType, data []byte) error {
		if typ == loop.CSI {
			switch data[len(data)-1] {
			case 'c':
				lp.Quit(0)
			case 'R':
				if idx := bytes.IndexByte(data, ';'); idx > -1 {
					if xpos, e := strconv.Atoi(utils.UnsafeBytesToString(data[idx+1 : len(data)-1])); e == nil {
						t := tests[current_test_idx]
						if len(t.actual_cursor_positions) >= len(t.expected_cursor_positions) && current_test_idx+1 < len(tests) {
							current_test_idx += 1
							t = tests[current_test_idx]
						}
						t.actual_cursor_positions = append(t.actual_cursor_positions, xpos-1)
					}
				}
			}
		}
		return nil
	}
	if err = lp.Run(); err != nil {
		return err
	}
	return show_results(tests)
}

func show_results(tests []*test_struct) (err error) {
	num_failures := 0
	for _, t := range tests {
		if diff := cmp.Diff(t.expected_cursor_positions, t.actual_cursor_positions); diff != "" {
			fmt.Printf("\x1b[31mTest number %d failed\x1b[39m: %s\n", t.num, t.description)
			fmt.Println(diff)
			num_failures++
		}
	}
	if num_failures > 0 {
		err = fmt.Errorf("%d out of %d tests failed.", num_failures, len(tests))
	} else {
		fmt.Println("All tests passed!")
	}
	return
}

func has_control_chars(text string) bool {
	for _, ch := range text {
		if ch < ' ' {
			return true
		}
	}
	return false
}

func main(allowed_tests *utils.Set[int]) (rc int, err error) {
	var tests []*test_struct
	if gb_tests, err := kitty.LoadGraphemeBreakTests(); err == nil {
		for _, t := range gb_tests {
			text := strings.Join(t.Data, "")
			rt, _ := json.Marshal(text)
			desc := fmt.Sprintf("Unicode GraphemeBreakTest: Text: %s Expected breaks:\n%s", string(rt), t.Comment)
			if has_control_chars(text) {
				continue
			}
			buf := strings.Builder{}
			buf.WriteString(" " + text + cursor_position_report + reset_line + " ")
			expected_cursor_positions := []int{1 + wcswidth.Stringwidth(text)}
			// Now test cursor position after each individual grapheme
			pos := 0
			for _, grapheme := range t.Data {
				buf.WriteString(grapheme + cursor_position_report)
				pos += wcswidth.Stringwidth(grapheme)
				expected_cursor_positions = append(expected_cursor_positions, 1+pos)
			}
			test := test_struct{num: len(tests) + 1, description: desc, payload: buf.String(), expected_cursor_positions: expected_cursor_positions}
			tests = append(tests, &test)
		}
		if allowed_tests.Len() > 0 {
			temp := make([]*test_struct, 0, len(tests))
			for _, t := range tests {
				if allowed_tests.Has(t.num) {
					temp = append(temp, t)
				}
			}
			tests = temp
		}
		if err = run_tests(tests); err != nil {
			return 1, err
		}
	} else {
		return 1, err
	}
	return
}

func WcswidthKittenEntryPoint(root *Command) {
	root.AddSubCommand(&Command{
		Name:            "__width_test__",
		Usage:           "[test number to run...]",
		HelpText:        "Test the terminal for compliance with the kitty text-sizing specification's splitting of text into cells. You can optionally specify specific test numbers to run.",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *Command, args []string) (rc int, err error) {
			allowed_tests := utils.NewSet[int]()
			for _, arg := range args {
				if x, err := strconv.Atoi(arg); err == nil {
					allowed_tests.Add(x)
				} else {
					return 1, fmt.Errorf("%s is not a valid test number", arg)
				}
			}
			return main(allowed_tests)
		},
	})
}
