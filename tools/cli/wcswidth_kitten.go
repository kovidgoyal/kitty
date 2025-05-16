package cli

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/google/go-cmp/cmp"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type cpos struct {
	x, y int
}

func cpos_from_report(csi string) (ans cpos, err error) {
	before, after, found := strings.Cut(csi, ";")
	if !found {
		return ans, fmt.Errorf("Malformed Cursor Position Report from terminal with no ;")
	}
	if ans.y, err = strconv.Atoi(before); err != nil {
		return ans, fmt.Errorf("Malformed Cursor Position Report from terminal: %s", csi)
	}
	if ans.x, err = strconv.Atoi(after); err != nil {
		return ans, fmt.Errorf("Malformed Cursor Position Report from terminal: %s", csi)
	}
	// convert 1-based indexing to zero based indexing
	ans.x--
	ans.y--
	return
}

type test_struct struct {
	description               string
	num                       int
	expected_cursor_positions []int
	actual_cursor_positions   []cpos
	payload                   string
	tester                    func(actual_cursor_positions []cpos, screen_width int) string
	payload_gen               func(width_in_cells int) string
}

const cursor_position_report = "\x1b[6n"
const reset_line = "\r\x1b[K"

func wrap_gen(width_in_cells int) string {
	return strings.Repeat(" ", width_in_cells-2) + "\U0001f1ee" + cursor_position_report + "\U0001f1f3" + cursor_position_report
}

func wrap_tester(actual_cursor_positions []cpos, screen_width int) string {
	if actual_cursor_positions[0].x != actual_cursor_positions[1].x {
		return fmt.Sprintf("The cursor moved after adding a combining char from: %v -> %v", actual_cursor_positions[0], actual_cursor_positions[1])
	}
	return ""
}

func run_tests(tests []*test_struct) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen)
	if err != nil {
		return err
	}
	num_reports := 0
	expected_num_reports := 0
	gen_payload := func(screen_width int) string {
		buf := strings.Builder{}
		buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToSet())
		for _, t := range tests {
			payload := t.payload
			if t.payload_gen != nil {
				payload = t.payload_gen(screen_width)
			}
			expected_num_reports += strings.Count(payload, cursor_position_report)
			buf.WriteString(payload)
			buf.WriteString(reset_line)
			if buf.Len() > 512*1024 {
				buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToReset())
				buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToSet())
			}
		}
		buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToReset())
		buf.WriteString("\x1b[c")
		return buf.String()
	}

	print_para := func(text string) {
		sz, _ := lp.ScreenSize()
		for _, line := range style.WrapTextAsLines(text, int(sz.WidthCells), style.WrapOptions{Trim_whitespace: true}) {
			lp.Println(line)
		}
		lp.Println()
	}
	screen_width := 80
	lp.OnInitialize = func() (string, error) {
		sz, _ := lp.ScreenSize()
		screen_width = int(sz.WidthCells)
		print_para("These tests work by sending text to the terminal and then querying it for its cursor position. Every test is thus different strings sent to the terminal along with a list of expected cursor positions after each string. A failure means the actual cursor position was different from the expected one. A failure where the first expected cursor position is correct but subsequent ones are not, means that the complete string was rendered at the correct width but individual graphemes from the string were not.")
		print_para("The individual test descriptions use the character ÷ to indicate a position where a break is expected to occur and the character × to indicate a position where no break should happen. ")
		lp.Printf("Running %d tests, please wait...\n", len(tests))
		lp.SaveCursorPosition()
		lp.SetCursorVisible(false)

		lp.QueueWriteString(gen_payload(screen_width))
		return "", err
	}
	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		lp.RestoreCursorPosition()
		lp.ClearToEndOfScreen()
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
					if cpos, err := cpos_from_report(utils.UnsafeBytesToString(data[:len(data)-1])); err != nil {
						return err
					} else {
						num_reports++
						t := tests[current_test_idx]
						if len(t.actual_cursor_positions) >= len(t.expected_cursor_positions) && current_test_idx+1 < len(tests) {
							current_test_idx += 1
							t = tests[current_test_idx]
						}
						t.actual_cursor_positions = append(t.actual_cursor_positions, cpos)
					}
				}
			}
		}
		return nil
	}
	if err = lp.Run(); err != nil {
		return err
	}
	if num_reports != expected_num_reports {
		return fmt.Errorf("Terminal did not report the cursor position as many times as expected. %d != %d", expected_num_reports, num_reports)
	}
	return show_results(tests, screen_width)
}

func show_results(tests []*test_struct, screen_width int) (err error) {
	num_failures := 0
	for _, t := range tests {
		diff := ""
		if t.tester == nil {
			ac := make([]int, len(t.actual_cursor_positions))
			for i, cp := range t.actual_cursor_positions {
				ac[i] = cp.x
			}
			diff = cmp.Diff(t.expected_cursor_positions, ac)
		} else {
			diff = t.tester(t.actual_cursor_positions, screen_width)
		}
		if diff != "" {
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

func create_tests(gb_tests []kitty.GraphemeBreakTest, width_in_cells int) (tests []*test_struct) {
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
	test := test_struct{
		num: len(tests) + 1, description: "Check that combining characters are merged into last cell even when cursor is on the next line",
		payload_gen: wrap_gen, tester: wrap_tester}
	tests = append(tests, &test)
	return
}

func main(allowed_tests *utils.Set[int]) (rc int, err error) {
	term, err := tty.OpenControllingTerm()
	if err != nil {
		return 1, fmt.Errorf("Could not open controlling terminal with error: %w", err)
	}
	sz, err := term.GetSize()
	term.Close()
	if err != nil {
		return 1, fmt.Errorf("Could not get size of controlling terminal with error: %w", err)
	}
	width_in_cells := int(sz.Col)
	if gb_tests, err := kitty.LoadGraphemeBreakTests(); err == nil {
		tests := create_tests(gb_tests, width_in_cells)
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
