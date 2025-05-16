// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"container/list"
	"fmt"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
	"strconv"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func new_rl() *Readline {
	lp, _ := loop.New()
	rl := New(lp, RlInit{Prompt: "$$ "})
	rl.screen_width = 10
	rl.screen_height = 100
	return rl
}

func test_func(t *testing.T) func(string, func(*Readline), ...string) *Readline {
	return func(initial string, prepare func(rl *Readline), expected ...string) *Readline {
		rl := new_rl()
		rl.add_text(initial)
		if prepare != nil {
			prepare(rl)
		}
		if len(expected) > 0 {
			if expected[0] != rl.text_upto_cursor_pos() {
				t.Fatalf("Text upto cursor pos not as expected for: %#v\n%#v != %#v", initial, expected[0], rl.text_upto_cursor_pos())
			}
		}
		if len(expected) > 1 {
			if expected[1] != rl.text_after_cursor_pos() {
				t.Fatalf("Text after cursor pos not as expected for: %#v\n%#v != %#v", initial, expected[1], rl.text_after_cursor_pos())
			}
		}
		if len(expected) > 2 {
			if expected[2] != rl.all_text() {
				t.Fatalf("Text not as expected for: %#v\n%#v != %#v", initial, expected[2], rl.all_text())
			}
		}
		return rl
	}

}

func TestAddText(t *testing.T) {
	dt := test_func(t)
	dt("test", nil, "test", "", "test")
	dt("1234\n", nil, "1234\n", "", "1234\n")
	dt("abcd", func(rl *Readline) {
		rl.input_state.cursor.X = 2
		rl.add_text("12")
	}, "ab12", "cd", "ab12cd")
	dt("abcd", func(rl *Readline) {
		rl.input_state.cursor.X = 2
		rl.add_text("12\n34")
	}, "ab12\n34", "cd", "ab12\n34cd")
	dt("abcd\nxyz", func(rl *Readline) {
		rl.input_state.cursor.X = 2
		rl.add_text("12\n34")
	}, "abcd\nxy12\n34", "z", "abcd\nxy12\n34z")
}

func TestGetScreenLines(t *testing.T) {
	rl := new_rl()

	p := func(primary bool) Prompt {
		if primary {
			return rl.prompt
		}
		return rl.continuation_prompt
	}

	tsl := func(expected ...ScreenLine) {
		q := rl.get_screen_lines()
		actual := make([]ScreenLine, len(q))
		for i, x := range q {
			actual[i] = *x
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Did not get expected screen lines for: %#v and cursor: %+v\n%s", rl.AllText(), rl.input_state.cursor, diff)
		}
	}
	tsl(ScreenLine{Prompt: p(true), CursorCell: 3, AfterLineBreak: true})
	rl.add_text("123")
	tsl(ScreenLine{Prompt: p(true), CursorCell: 6, Text: "123", CursorTextPos: 3, TextLengthInCells: 3, AfterLineBreak: true})
	rl.add_text("456")
	tsl(ScreenLine{Prompt: p(true), CursorCell: 9, Text: "123456", CursorTextPos: 6, TextLengthInCells: 6, AfterLineBreak: true})
	rl.add_text("7")
	tsl(
		ScreenLine{Prompt: p(true), CursorCell: -1, Text: "1234567", CursorTextPos: -1, TextLengthInCells: 7, AfterLineBreak: true},
		ScreenLine{OffsetInParentLine: 7},
	)
	rl.add_text("89")
	tsl(
		ScreenLine{Prompt: p(true), CursorCell: -1, Text: "1234567", CursorTextPos: -1, TextLengthInCells: 7, AfterLineBreak: true},
		ScreenLine{OffsetInParentLine: 7, Text: "89", CursorCell: 2, TextLengthInCells: 2, CursorTextPos: 2},
	)
	rl.ResetText()
	rl.add_text("123\n456abcdeXYZ")
	tsl(
		ScreenLine{Prompt: p(true), CursorCell: -1, Text: "123", CursorTextPos: -1, TextLengthInCells: 3, AfterLineBreak: true},
		ScreenLine{ParentLineNumber: 1, Prompt: p(false), Text: "456abcde", TextLengthInCells: 8, CursorCell: -1, CursorTextPos: -1, AfterLineBreak: true},
		ScreenLine{OffsetInParentLine: 8, ParentLineNumber: 1, TextLengthInCells: 3, CursorCell: 3, CursorTextPos: 3, Text: "XYZ"},
	)
	rl.input_state.cursor = Position{X: 2}
	tsl(
		ScreenLine{Prompt: p(true), CursorCell: 5, Text: "123", CursorTextPos: 2, TextLengthInCells: 3, AfterLineBreak: true},
		ScreenLine{ParentLineNumber: 1, Prompt: p(false), Text: "456abcde", TextLengthInCells: 8, CursorCell: -1, CursorTextPos: -1, AfterLineBreak: true},
		ScreenLine{OffsetInParentLine: 8, ParentLineNumber: 1, TextLengthInCells: 3, CursorCell: -1, CursorTextPos: -1, Text: "XYZ"},
	)
	rl.input_state.cursor = Position{X: 2, Y: 1}
	tsl(
		ScreenLine{Prompt: p(true), CursorCell: -1, Text: "123", CursorTextPos: -1, TextLengthInCells: 3, AfterLineBreak: true},
		ScreenLine{ParentLineNumber: 1, Prompt: p(false), Text: "456abcde", TextLengthInCells: 8, CursorCell: 4, CursorTextPos: 2, AfterLineBreak: true},
		ScreenLine{OffsetInParentLine: 8, ParentLineNumber: 1, TextLengthInCells: 3, CursorCell: -1, CursorTextPos: -1, Text: "XYZ"},
	)
	rl.input_state.cursor = Position{X: 8, Y: 1}
	tsl(
		ScreenLine{Prompt: p(true), CursorCell: -1, Text: "123", CursorTextPos: -1, TextLengthInCells: 3, AfterLineBreak: true},
		ScreenLine{ParentLineNumber: 1, Prompt: p(false), Text: "456abcde", TextLengthInCells: 8, CursorCell: -1, CursorTextPos: -1, AfterLineBreak: true},
		ScreenLine{OffsetInParentLine: 8, ParentLineNumber: 1, TextLengthInCells: 3, CursorCell: 0, CursorTextPos: 0, Text: "XYZ"},
	)
	rl.ResetText()
	rl.add_text("1234567\nabc")
	rl.input_state.cursor = Position{X: 7}
	tsl(
		ScreenLine{Prompt: p(true), CursorCell: -1, Text: "1234567", CursorTextPos: -1, TextLengthInCells: 7, AfterLineBreak: true},
		ScreenLine{ParentLineNumber: 1, Prompt: p(false), Text: "abc", CursorCell: 2, TextLengthInCells: 3, CursorTextPos: 0, AfterLineBreak: true},
	)
}

func TestCursorMovement(t *testing.T) {
	dt := test_func(t)

	left := func(rl *Readline, amt uint, moved_amt uint, traverse_line_breaks bool) {
		actual := rl.move_cursor_left(amt, traverse_line_breaks)
		if actual != moved_amt {
			t.Fatalf("Failed to move cursor by %#v\nactual != expected: %#v != %#v", amt, actual, moved_amt)
		}
	}
	dt("one\ntwo", func(rl *Readline) {
		left(rl, 2, 2, false)
	}, "one\nt", "wo")
	dt("one\ntwo", func(rl *Readline) {
		left(rl, 4, 3, false)
	}, "one\n", "two")
	dt("one\ntwo", func(rl *Readline) {
		left(rl, 4, 4, true)
	}, "one", "\ntwo")
	dt("one\ntwo", func(rl *Readline) {
		left(rl, 7, 7, true)
	}, "", "one\ntwo")
	dt("one\ntwo", func(rl *Readline) {
		left(rl, 10, 7, true)
	}, "", "one\ntwo")
	dt("one😀", func(rl *Readline) {
		left(rl, 1, 1, false)
	}, "one", "😀")
	dt("oneà", func(rl *Readline) {
		left(rl, 1, 1, false)
	}, "one", "à")

	right := func(rl *Readline, amt uint, moved_amt uint, traverse_line_breaks bool) {
		rl.input_state.cursor.Y = 0
		rl.input_state.cursor.X = 0
		actual := rl.move_cursor_right(amt, traverse_line_breaks)
		if actual != moved_amt {
			t.Fatalf("Failed to move cursor by %d\nactual != expected: %d != %d", amt, actual, moved_amt)
		}
	}
	dt("one\ntwo", func(rl *Readline) {
		right(rl, 2, 2, false)
	}, "on", "e\ntwo")
	dt("one\ntwo", func(rl *Readline) {
		right(rl, 4, 3, false)
	}, "one", "\ntwo")
	dt("one\ntwo", func(rl *Readline) {
		right(rl, 4, 4, true)
	}, "one\n", "two")
	dt("😀one", func(rl *Readline) {
		right(rl, 1, 1, false)
	}, "😀", "one")
	dt("àb", func(rl *Readline) {
		right(rl, 1, 1, false)
	}, "à", "b")

	rl := new_rl()

	vert := func(amt int, moved_amt int, text_upto_cursor_pos string, initials ...Position) {
		initial := Position{}
		if len(initials) > 0 {
			initial = initials[0]
		}
		rl.input_state.cursor = initial
		actual := rl.move_cursor_vertically(amt)
		if actual != moved_amt {
			t.Fatalf("Failed to move cursor by %#v for: %#v \nactual != expected: %#v != %#v", amt, rl.AllText(), actual, moved_amt)
		}
		if diff := cmp.Diff(text_upto_cursor_pos, rl.text_upto_cursor_pos()); diff != "" {
			t.Fatalf("Did not get expected screen lines for: %#v and cursor: %+v\n%s", rl.AllText(), initial, diff)
		}
	}

	rl.ResetText()
	rl.add_text("1234567xy\nabcd\n123")
	vert(-1, -1, "1234567xy\nabc", Position{X: 3, Y: 2})
	vert(-2, -2, "1234567xy", Position{X: 3, Y: 2})
	vert(-30, -3, "123", Position{X: 3, Y: 2})

	rl.ResetText()
	rl.add_text("o\u0300ne  two three\nfour five")

	wf := func(amt uint, expected_amt uint, text_before_cursor string) {
		pos := rl.input_state.cursor
		actual_amt := rl.move_to_end_of_word(amt, true, has_word_chars)
		if actual_amt != expected_amt {
			t.Fatalf("Failed to move to word end, expected amt (%d) != actual amt (%d)", expected_amt, actual_amt)
		}
		if diff := cmp.Diff(text_before_cursor, rl.TextBeforeCursor()); diff != "" {
			t.Fatalf("Did not get expected text before cursor for: %#v and cursor: %+v\n%s", rl.AllText(), pos, diff)
		}
	}
	rl.input_state.cursor = Position{}
	wf(1, 1, "òne")
	wf(1, 1, "òne  two")
	wf(1, 1, "òne  two three")
	wf(1, 1, "òne  two three\nfour")
	wf(1, 1, "òne  two three\nfour five")
	wf(1, 0, "òne  two three\nfour five")
	rl.input_state.cursor = Position{}
	wf(5, 5, "òne  two three\nfour five")
	rl.input_state.cursor = Position{X: 5}
	wf(1, 1, "òne  two")

	wb := func(amt uint, expected_amt uint, text_before_cursor string) {
		pos := rl.input_state.cursor
		actual_amt := rl.move_to_start_of_word(amt, true, has_word_chars)
		if actual_amt != expected_amt {
			t.Fatalf("Failed to move to word end, expected amt (%d) != actual amt (%d)", expected_amt, actual_amt)
		}
		if diff := cmp.Diff(text_before_cursor, rl.TextBeforeCursor()); diff != "" {
			t.Fatalf("Did not get expected text before cursor for: %#v and cursor: %+v\n%s", rl.AllText(), pos, diff)
		}
	}
	rl.input_state.cursor = Position{X: 2}
	wb(1, 1, "")
	rl.input_state.cursor = Position{X: 8, Y: 1}
	wb(1, 1, "òne  two three\nfour ")
	wb(1, 1, "òne  two three\n")
	wb(1, 1, "òne  two ")
	wb(1, 1, "òne  ")
	wb(1, 1, "")
	wb(1, 0, "")
	rl.input_state.cursor = Position{X: 8, Y: 1}
	wb(5, 5, "")
	rl.input_state.cursor = Position{X: 5}
	wb(1, 1, "")

}

func TestYanking(t *testing.T) {
	rl := new_rl()

	as_slice := func(l *list.List) []string {
		ans := make([]string, 0, l.Len())
		for e := l.Front(); e != nil; e = e.Next() {
			ans = append(ans, e.Value.(string))
		}
		return ans
	}

	assert_items := func(expected ...string) {
		if diff := cmp.Diff(expected, as_slice(rl.kill_ring.items)); diff != "" {
			t.Fatalf("kill ring items not as expected\n%s", diff)
		}
	}
	assert_text := func(expected string) {
		if diff := cmp.Diff(expected, rl.all_text()); diff != "" {
			t.Fatalf("text not as expected:\n%s", diff)
		}
	}

	rl.add_text("1 2 3\none two three")
	rl.perform_action(ActionKillToStartOfLine, 1)
	assert_items("one two three")
	rl.perform_action(ActionCursorUp, 1)
	rl.perform_action(ActionKillToEndOfLine, 1)
	assert_items("1 2 3", "one two three")
	rl.perform_action(ActionYank, 1)
	assert_text("1 2 3\n")
	rl.perform_action(ActionYank, 1)
	assert_text("1 2 31 2 3\n")
	rl.perform_action(ActionPopYank, 1)
	assert_text("1 2 3one two three\n")
	rl.perform_action(ActionPopYank, 1)
	assert_text("1 2 31 2 3\n")

	rl.ResetText()
	rl.kill_ring.clear()
	rl.add_text("one two three")
	rl.perform_action(ActionMoveToStartOfLine, 1)
	rl.perform_action(ActionKillNextWord, 1)
	assert_items("one")
	assert_text(" two three")
	rl.perform_action(ActionKillNextWord, 1)
	assert_items("one two")
	assert_text(" three")
	rl.perform_action(ActionCursorRight, 1)
	rl.perform_action(ActionKillNextWord, 1)
	assert_items("three", "one two")
	assert_text(" ")
}

func TestEraseChars(t *testing.T) {
	dt := test_func(t)

	backspace := func(rl *Readline, amt uint, erased_amt uint, traverse_line_breaks bool) {
		actual := rl.erase_chars_before_cursor(amt, traverse_line_breaks)
		if actual != erased_amt {
			t.Fatalf("Failed to move cursor by %#v\nactual != expected: %d != %d", amt, actual, erased_amt)
		}
	}
	dt("one\ntwo", func(rl *Readline) {
		backspace(rl, 2, 2, false)
	}, "one\nt", "")
	dt("one\ntwo", func(rl *Readline) {
		rl.input_state.cursor.X = 1
		backspace(rl, 2, 1, false)
	}, "one\n", "wo")
	dt("one\ntwo", func(rl *Readline) {
		rl.input_state.cursor.X = 1
		backspace(rl, 2, 2, true)
	}, "one", "wo")
	dt("a😀", func(rl *Readline) {
		backspace(rl, 1, 1, false)
	}, "a", "")
	dt("bà", func(rl *Readline) {
		backspace(rl, 1, 1, false)
	}, "b", "")

	del := func(rl *Readline, amt uint, erased_amt uint, traverse_line_breaks bool) {
		rl.input_state.cursor.Y = 0
		rl.input_state.cursor.X = 0
		actual := rl.erase_chars_after_cursor(amt, traverse_line_breaks)
		if actual != erased_amt {
			t.Fatalf("Failed to move cursor by %#v\nactual != expected: %d != %d", amt, actual, erased_amt)
		}
	}
	dt("one\ntwo", func(rl *Readline) {
		del(rl, 2, 2, false)
	}, "", "e\ntwo")
	dt("😀a", func(rl *Readline) {
		del(rl, 1, 1, false)
	}, "", "a")
	dt("àb", func(rl *Readline) {
		del(rl, 1, 1, false)
	}, "", "b")

	dt("one\ntwo\nthree", func(rl *Readline) {
		rl.erase_between(Position{X: 1}, Position{X: 2, Y: 2})
	}, "oree", "")
	dt("one\ntwo\nthree", func(rl *Readline) {
		rl.input_state.cursor.X = 1
		rl.erase_between(Position{X: 1}, Position{X: 2, Y: 2})
	}, "o", "ree")
	dt("one\ntwo\nthree", func(rl *Readline) {
		rl.input_state.cursor = Position{X: 1, Y: 1}
		rl.erase_between(Position{X: 1}, Position{X: 2, Y: 2})
	}, "o", "ree")
	dt("one\ntwo\nthree", func(rl *Readline) {
		rl.input_state.cursor = Position{X: 1, Y: 0}
		rl.erase_between(Position{X: 1}, Position{X: 2, Y: 2})
	}, "o", "ree")
	dt("one\ntwo\nthree", func(rl *Readline) {
		rl.input_state.cursor = Position{X: 0, Y: 0}
		rl.erase_between(Position{X: 1}, Position{X: 2, Y: 2})
	}, "", "oree")
}

func TestNumberArgument(t *testing.T) {
	rl := new_rl()
	rl.screen_width = 100

	test := func(ac Action, before_cursor, after_cursor string) {
		rl.dispatch_key_action(ac)
		if diff := cmp.Diff(before_cursor, rl.text_upto_cursor_pos()); diff != "" {
			t.Fatalf("The text before the cursor was not as expected for action: %#v\n%s", ac, diff)
		}
		if diff := cmp.Diff(after_cursor, rl.text_after_cursor_pos()); diff != "" {
			t.Fatalf("The text after the cursor was not as expected for action: %#v\n%s", ac, diff)
		}
	}
	sw := func(num int) {
		q := rl.format_arg_prompt(strconv.Itoa(num))
		for _, sl := range rl.get_screen_lines() {
			if num <= 0 && !strings.Contains(sl.Prompt.Text, "$$") {
				t.Fatalf("arg prompt unexpectedly present for: %#v", rl.AllText())
			}
			if num > 0 && !strings.Contains(sl.Prompt.Text, q) {
				t.Fatalf("arg prompt unexpectedly not present for: %#v prompt: %#v", rl.AllText(), sl.Prompt.Text)
			}
		}
	}

	sw(0)
	rl.dispatch_key_action(ActionNumericArgumentDigit1)
	sw(1)
	rl.dispatch_key_action(ActionNumericArgumentDigit0)
	sw(10)
	rl.text_to_be_added = "x"
	test(ActionAddText, "xxxxxxxxxx", "")
	sw(0)
	test(ActionNumericArgumentDigit0, "xxxxxxxxxx0", "")
	sw(0)
	rl.dispatch_key_action(ActionNumericArgumentDigit1)
	test(ActionNumericArgumentDigitMinus, "xxxxxxxxxx0-", "")
	sw(0)
	rl.dispatch_key_action(ActionNumericArgumentDigit1)
	sw(1)
	rl.dispatch_key_action(ActionNumericArgumentDigit1)
	sw(11)
	test(ActionCursorLeft, "x", "xxxxxxxxx0-")
	sw(0)
}

func TestHistory(t *testing.T) {
	rl := new_rl()

	add_item := func(x string) {
		rl.history.AddItem(x, 0)
	}
	add_item("a one")
	add_item("a two")
	add_item("b three")
	add_item("b four")

	test := func(ac Action, before_cursor, after_cursor string) {
		rl.perform_action(ac, 1)
		if diff := cmp.Diff(before_cursor, rl.text_upto_cursor_pos()); diff != "" {
			t.Fatalf("The text before the cursor was not as expected for action: %#v\n%s", ac, diff)
		}
		if diff := cmp.Diff(after_cursor, rl.text_after_cursor_pos()); diff != "" {
			t.Fatalf("The text after the cursor was not as expected for action: %#v\n%s", ac, diff)
		}
	}

	test(ActionHistoryPreviousOrCursorUp, "b four", "")
	test(ActionHistoryPreviousOrCursorUp, "b three", "")
	test(ActionHistoryPrevious, "a two", "")
	test(ActionHistoryPrevious, "a one", "")
	test(ActionHistoryPrevious, "a one", "")
	test(ActionHistoryNext, "a two", "")
	test(ActionHistoryNext, "b three", "")
	test(ActionHistoryNext, "b four", "")
	test(ActionHistoryNext, "", "")
	test(ActionHistoryNext, "", "")

	test(ActionHistoryPrevious, "b four", "")
	test(ActionHistoryPrevious, "b three", "")
	test(ActionHistoryNext, "b four", "")

	rl.ResetText()
	rl.add_text("a")
	test(ActionHistoryPrevious, "a two", "")
	test(ActionHistoryPrevious, "a one", "")
	test(ActionHistoryPrevious, "a one", "")
	test(ActionHistoryNext, "a two", "")
	test(ActionHistoryNext, "a", "")
	test(ActionHistoryNext, "a", "")

	ah := func(before_cursor, after_cursor string) {
		ab := rl.text_upto_cursor_pos()
		aa := rl.text_after_cursor_pos()
		if diff := cmp.Diff(before_cursor, ab); diff != "" {
			t.Fatalf("Text before cursor not as expected:\n%s", diff)
		}
		if diff := cmp.Diff(after_cursor, aa); diff != "" {
			t.Fatalf("Text after cursor not as expected:\n%s", diff)
		}
	}
	add_item("xyz1")
	add_item("xyz2")
	add_item("xyz11")
	rl.perform_action(ActionHistoryIncrementalSearchBackwards, 1)
	ah("", "")

	rl.text_to_be_added = "z"
	rl.perform_action(ActionAddText, 1)
	ah("xy", "z11")
	rl.text_to_be_added = "2"
	rl.perform_action(ActionAddText, 1)
	ah("xy", "z2")
	rl.text_to_be_added = "m"
	rl.perform_action(ActionAddText, 1)
	ah("No matches for: z2m", "")
	rl.perform_action(ActionBackspace, 1)
	ah("xy", "z2")
	rl.perform_action(ActionBackspace, 1)
	ah("xy", "z2")
	rl.perform_action(ActionHistoryIncrementalSearchBackwards, 1)
	ah("xy", "z1")
	rl.perform_action(ActionHistoryIncrementalSearchBackwards, 1)
	ah("xy", "z1")
	rl.perform_action(ActionHistoryIncrementalSearchForwards, 1)
	ah("xy", "z2")
	rl.perform_action(ActionTerminateHistorySearchAndRestore, 1)
	ah("a", "")
}

func TestReadlineCompletion(t *testing.T) {
	completer := func(before_cursor, after_cursor string) (ans *cli.Completions) {
		root := cli.NewRootCommand()
		c := root.AddSubCommand(&cli.Command{Name: "test-completion"})
		c.AddSubCommand(&cli.Command{Name: "a1"})
		c.AddSubCommand(&cli.Command{Name: "a11"})
		c.AddSubCommand(&cli.Command{Name: "a2"})
		prefix := c.Name + " "
		text := prefix + before_cursor
		argv, position_of_last_arg := shlex.SplitForCompletion(text)
		if len(argv) == 0 || position_of_last_arg < len(prefix) {
			return
		}
		ans = root.GetCompletions(argv, nil)
		ans.CurrentWordIdx = position_of_last_arg - len(prefix)
		return

	}
	rl := new_rl()
	rl.completions.completer = completer

	ah := func(before_cursor, after_cursor string) {
		ab := rl.text_upto_cursor_pos()
		aa := rl.text_after_cursor_pos()
		if diff := cmp.Diff(before_cursor, ab); diff != "" {
			t.Fatalf("Text before cursor not as expected:\n%s", diff)
		}
		if diff := cmp.Diff(after_cursor, aa); diff != "" {
			t.Fatalf("Text after cursor not as expected:\n%s", diff)
		}
		actual, _ := rl.completion_screen_lines()
		expected := []string{"a1 a11 a2 "}
		if diff := cmp.Diff(expected, actual[1:]); diff != "" {
			t.Fatalf("Completion screen lines not as expected:\n%s", diff)
		}
	}
	rl.add_text("a")
	rl.perform_action(ActionCompleteForward, 1)
	ah("a", "")
	rl.perform_action(ActionCompleteForward, 1)
	ah("a1 ", "")
	rl.perform_action(ActionCompleteForward, 1)
	ah("a11 ", "")
	rl.perform_action(ActionCompleteForward, 1)
	ah("a2 ", "")
	rl.perform_action(ActionCompleteBackward, 1)
	ah("a11 ", "")
}
