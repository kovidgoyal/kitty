// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"container/list"
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

const ST = "\x1b\\"
const PROMPT_MARK = "\x1b]133;"

type SyntaxHighlightFunction = func(text string, x, y int) string
type CompleterFunction = func(before_cursor, after_cursor string) *cli.Completions

type RlInit struct {
	Prompt                  string
	HistoryPath             string
	HistoryCount            int
	ContinuationPrompt      string
	EmptyContinuationPrompt bool
	DontMarkPrompts         bool
	SyntaxHighlighter       SyntaxHighlightFunction
	Completer               CompleterFunction
}

type Position struct {
	X int
	Y int
}

func (self Position) Less(other Position) bool {
	return self.Y < other.Y || (self.Y == other.Y && self.X < other.X)
}

type kill_ring struct {
	items *list.List
}

func (self *kill_ring) append_to_existing_item(text string) {
	e := self.items.Front()
	if e == nil {
		self.add_new_item(text)
	}
	e.Value = e.Value.(string) + text
}

func (self *kill_ring) add_new_item(text string) {
	if text != "" {
		self.items.PushFront(text)
	}
}

func (self *kill_ring) yank() string {
	e := self.items.Front()
	if e == nil {
		return ""
	}
	return e.Value.(string)
}

func (self *kill_ring) pop_yank() string {
	e := self.items.Front()
	if e == nil {
		return ""
	}
	self.items.MoveToBack(e)
	return self.yank()
}

func (self *kill_ring) clear() {
	self.items = self.items.Init()
}

type Prompt struct {
	Text   string
	Length int
}

type InputState struct {
	// Input lines
	lines []string
	// The cursor position in the text
	cursor Position
}

func (self InputState) copy() InputState {
	ans := self
	l := make([]string, len(self.lines))
	copy(l, self.lines)
	ans.lines = l
	return ans
}

type syntax_highlighted struct {
	lines                  []string
	src_for_last_highlight string
	highlighter            SyntaxHighlightFunction
	last_highlighter_name  string
}

type Readline struct {
	prompt, continuation_prompt Prompt

	mark_prompts bool
	loop         *loop.Loop
	history      *History
	kill_ring    kill_ring

	input_state InputState
	// The number of lines after the initial line on the screen
	cursor_y                    int
	screen_width, screen_height int
	last_yank_extent            struct {
		start, end Position
	}
	bracketed_paste_buffer strings.Builder
	last_action            Action
	history_matches        *HistoryMatches
	history_search         *HistorySearch
	keyboard_state         KeyboardState
	fmt_ctx                *markup.Context
	text_to_be_added       string
	syntax_highlighted     syntax_highlighted
	completions            completions
}

func (self *Readline) make_prompt(text string, is_secondary bool) Prompt {
	if self.mark_prompts {
		m := PROMPT_MARK + "A"
		if is_secondary {
			m += ";k=s"
		}
		text = m + ST + text
	}
	return Prompt{Text: text, Length: wcswidth.Stringwidth(text)}
}

func New(loop *loop.Loop, r RlInit) *Readline {
	hc := r.HistoryCount
	if hc == 0 {
		hc = 8192
	}
	ans := &Readline{
		mark_prompts: !r.DontMarkPrompts, fmt_ctx: markup.New(true),
		loop: loop, input_state: InputState{lines: []string{""}}, history: NewHistory(r.HistoryPath, hc),
		syntax_highlighted: syntax_highlighted{highlighter: r.SyntaxHighlighter},
		completions:        completions{completer: r.Completer},
		kill_ring:          kill_ring{items: list.New().Init()},
	}
	if ans.completions.completer == nil && r.HistoryPath != "" {
		ans.completions.completer = ans.HistoryCompleter
	}
	ans.prompt = ans.make_prompt(r.Prompt, false)
	t := ""
	if r.ContinuationPrompt != "" || !r.EmptyContinuationPrompt {
		t = r.ContinuationPrompt
		if t == "" {
			t = ans.fmt_ctx.Yellow(">") + " "
		}
	}
	ans.continuation_prompt = ans.make_prompt(t, true)
	return ans
}

func (self *Readline) HistoryCompleter(before_cursor, after_cursor string) *cli.Completions {
	return self.history_completer(before_cursor, after_cursor)
}

func (self *Readline) SetPrompt(prompt string) {
	self.prompt = self.make_prompt(prompt, false)
}

func (self *Readline) Shutdown() {
	self.history.Shutdown()
}

func (self *Readline) AddHistoryItem(hi HistoryItem) {
	self.history.merge_items(hi)
}

func (self *Readline) ResetText() {
	self.input_state = InputState{lines: []string{""}}
	self.last_action = ActionNil
	self.keyboard_state = KeyboardState{}
	self.history_search = nil
	self.completions.current = completion{}
	self.cursor_y = 0
}

func (self *Readline) ChangeLoopAndResetText(lp *loop.Loop) {
	self.loop = lp
	self.ResetText()
}

func (self *Readline) Start() {
	self.loop.SetCursorShape(loop.BAR_CURSOR, true)
	self.loop.StartBracketedPaste()
	self.Redraw()
}

func (self *Readline) End() {
	self.loop.SetCursorShape(loop.BLOCK_CURSOR, true)
	self.loop.EndBracketedPaste()
	self.loop.QueueWriteString("\r\n")
	if self.mark_prompts {
		self.loop.QueueWriteString(PROMPT_MARK + "C" + ST)
	}
}

func MarkOutputStart() string {
	return PROMPT_MARK + "C" + ST
}

func (self *Readline) Redraw() {
	self.loop.StartAtomicUpdate()
	self.RedrawNonAtomic()
	self.loop.EndAtomicUpdate()
}

func (self *Readline) RedrawNonAtomic() {
	self.redraw()
}

func (self *Readline) OnKeyEvent(event *loop.KeyEvent) error {
	err := self.handle_key_event(event)
	if err == ErrCouldNotPerformAction {
		err = nil
		self.loop.Beep()
	}
	return err
}

func (self *Readline) OnText(text string, from_key_event bool, in_bracketed_paste bool) error {
	if in_bracketed_paste {
		self.bracketed_paste_buffer.WriteString(text)
		return nil
	}
	if self.bracketed_paste_buffer.Len() > 0 {
		self.bracketed_paste_buffer.WriteString(text)
		text = self.bracketed_paste_buffer.String()
		self.bracketed_paste_buffer.Reset()
	}
	self.text_to_be_added = text
	return self.dispatch_key_action(ActionAddText)
}

func (self *Readline) TextBeforeCursor() string {
	return self.text_upto_cursor_pos()
}

func (self *Readline) TextAfterCursor() string {
	return self.text_after_cursor_pos()
}

func (self *Readline) AllText() string {
	return self.all_text()
}

func (self *Readline) SetText(text string) {
	self.set_text(text)
}

func (self *Readline) MoveCursorToEnd() bool {
	return self.move_to_end()
}

func (self *Readline) CursorAtEndOfLine() bool {
	return self.input_state.cursor.X >= len(self.input_state.lines[self.input_state.cursor.Y])
}

func (self *Readline) ClearCachedScreenSize() {
	self.screen_width, self.screen_height = 0, 0
}

func (self *Readline) OnResize(old_size loop.ScreenSize, new_size loop.ScreenSize) error {
	self.ClearCachedScreenSize()
	self.Redraw()
	return nil
}
