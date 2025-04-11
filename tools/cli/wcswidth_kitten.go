package cli

import (
	"bytes"
	"fmt"
	"strconv"
	"strings"

	"github.com/google/go-cmp/cmp"

	"kitty"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"kitty/tools/wcswidth"
)

var _ = fmt.Print

type test_struct struct {
	description               string
	expected_cursor_positions []int
	actual_cursor_positions   []int
	payload                   string
}

const cursor_position_report = "\x1b[6n"

func run_tests(tests []*test_struct) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen)
	if err != nil {
		return err
	}
	buf := strings.Builder{}
	buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToSet())
	for _, t := range tests {
		buf.WriteString(t.payload)
		buf.WriteString("\r\x1b[K")
		if buf.Len() > 512*1024 {
			buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToReset())
			buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToSet())
		}
	}
	buf.WriteString(loop.PENDING_UPDATE.EscapeCodeToReset())
	buf.WriteString("\x1b[c")

	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
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
			fmt.Println("\x1b[31mTest failed\x1b[39m:", t.description)
			fmt.Println(diff)
			num_failures++
		}
	}
	if num_failures > 0 {
		err = fmt.Errorf("%d out of %d tests failed.", num_failures, len(tests))
	} else {
		fmt.Printf("All %d tests passed!\n", len(tests))
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

func main() (rc int, err error) {
	var tests []*test_struct
	if gb_tests, err := kitty.LoadGraphemeBreakTests(); err == nil {
		for i, t := range gb_tests {
			desc := fmt.Sprintf("Unicode GraphemeBreakTest: #%d (%s)", i, t.Comment)
			text := strings.Join(t.Data, "")
			if has_control_chars(text) {
				continue
			}
			payload := " " + text + cursor_position_report
			test := test_struct{description: desc, payload: payload, expected_cursor_positions: []int{1 + wcswidth.Stringwidth(text)}}
			tests = append(tests, &test)
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
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *Command, args []string) (rc int, err error) {
			if len(args) != 0 {
				return 1, fmt.Errorf("Usage: __width_test__")
			}
			return main()
		},
	})
}
