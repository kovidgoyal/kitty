// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"fmt"

	"kitty/tools/tui/loop"
	"kitty/tools/wcswidth"
)

var _ = fmt.Print

const ST = "\x1b\\"
const PROMPT_MARK = "\x1b]133;"

type RlInit struct {
	Prompt                  string
	ContinuationPrompt      string
	EmptyContinuationPrompt bool
	DontMarkPrompts         bool
}

type Readline struct {
	prompt                  string
	prompt_len              int
	continuation_prompt     string
	continuation_prompt_len int
	mark_prompts            bool
	loop                    *loop.Loop

	// The number of lines after the initial line
	cursor_y int
	// Input lines
	lines []string
	// The line the cursor is at currently
	cursor_line int
	// The offset into the text of the cursor line
	cursor_pos_in_line int
}

func New(loop *loop.Loop, r RlInit) *Readline {
	ans := &Readline{
		prompt: r.Prompt, prompt_len: wcswidth.Stringwidth(r.Prompt), mark_prompts: !r.DontMarkPrompts,
		loop: loop, lines: []string{""},
	}
	if r.ContinuationPrompt != "" || !r.EmptyContinuationPrompt {
		ans.continuation_prompt = r.ContinuationPrompt
		if ans.continuation_prompt == "" {
			ans.continuation_prompt = "> "
		}
	}
	if ans.mark_prompts {
		ans.prompt = PROMPT_MARK + "A" + ST + ans.prompt
		ans.continuation_prompt = PROMPT_MARK + "A;k=s" + ST + ans.continuation_prompt
	}
	return ans
}

func (self *Readline) Start() {
	self.loop.SetCursorShape(loop.BAR_CURSOR, true)
	self.loop.StartBracketedPaste()
	self.Redraw()
}

func (self *Readline) Redraw() {
	self.loop.StartAtomicUpdate()
	self.RedrawNonAtomic()
	self.loop.EndAtomicUpdate()
}

func (self *Readline) RedrawNonAtomic() {
	self.redraw()
}

func (self *Readline) End() {
	self.loop.EndBracketedPaste()
	self.loop.QueueWriteString("\r\n")
	self.loop.SetCursorShape(loop.BLOCK_CURSOR, true)
	if self.mark_prompts {
		self.loop.QueueWriteString(PROMPT_MARK + "C" + ST)
	}
}

func (self *Readline) OnKeyEvent(event *loop.KeyEvent) error {
	return self.handle_key_event(event)
}

func (self *Readline) OnText(text string, from_key_event bool, in_bracketed_paste bool) error {
	self.add_text(text)
	return nil
}
