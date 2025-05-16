// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"errors"
	"fmt"
	"strconv"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/shortcuts"
)

var _ = fmt.Print

type ShortcutMap = shortcuts.ShortcutMap[Action]

type KeyboardState struct {
	active_shortcut_maps     []*ShortcutMap
	current_pending_keys     []string
	current_numeric_argument string
}

var _default_shortcuts *ShortcutMap

func default_shortcuts() *ShortcutMap {
	if _default_shortcuts == nil {
		sm := shortcuts.New[Action]()
		sm.AddOrPanic(ActionBackspace, "backspace")
		sm.AddOrPanic(ActionBackspace, "shift+backspace")
		sm.AddOrPanic(ActionBackspace, "ctrl+h")
		sm.AddOrPanic(ActionDelete, "delete")

		sm.AddOrPanic(ActionMoveToStartOfLine, "home")
		sm.AddOrPanic(ActionMoveToStartOfLine, "ctrl+a")

		sm.AddOrPanic(ActionMoveToEndOfLine, "end")
		sm.AddOrPanic(ActionMoveToEndOfLine, "ctrl+e")

		sm.AddOrPanic(ActionMoveToStartOfDocument, "ctrl+home")
		sm.AddOrPanic(ActionMoveToEndOfDocument, "ctrl+end")

		sm.AddOrPanic(ActionMoveToEndOfWord, "alt+f")
		sm.AddOrPanic(ActionMoveToEndOfWord, "ctrl+right")
		sm.AddOrPanic(ActionMoveToEndOfWord, "alt+right")
		sm.AddOrPanic(ActionMoveToStartOfWord, "ctrl+left")
		sm.AddOrPanic(ActionMoveToStartOfWord, "alt+left")
		sm.AddOrPanic(ActionMoveToStartOfWord, "alt+b")

		sm.AddOrPanic(ActionCursorLeft, "left")
		sm.AddOrPanic(ActionCursorLeft, "ctrl+b")
		sm.AddOrPanic(ActionCursorRight, "right")
		sm.AddOrPanic(ActionCursorRight, "ctrl+f")

		sm.AddOrPanic(ActionClearScreen, "ctrl+l")
		sm.AddOrPanic(ActionAbortCurrentLine, "ctrl+c")
		sm.AddOrPanic(ActionAbortCurrentLine, "ctrl+g")

		sm.AddOrPanic(ActionEndInput, "ctrl+d")
		sm.AddOrPanic(ActionAcceptInput, "enter")

		sm.AddOrPanic(ActionKillToEndOfLine, "ctrl+k")
		sm.AddOrPanic(ActionKillToStartOfLine, "ctrl+x")
		sm.AddOrPanic(ActionKillToStartOfLine, "ctrl+u")
		sm.AddOrPanic(ActionKillNextWord, "alt+d")
		sm.AddOrPanic(ActionKillPreviousWord, "alt+backspace")
		sm.AddOrPanic(ActionKillPreviousSpaceDelimitedWord, "ctrl+w")
		sm.AddOrPanic(ActionYank, "ctrl+y")
		sm.AddOrPanic(ActionPopYank, "alt+y")

		sm.AddOrPanic(ActionHistoryPreviousOrCursorUp, "up")
		sm.AddOrPanic(ActionHistoryNextOrCursorDown, "down")
		sm.AddOrPanic(ActionHistoryPrevious, "ctrl+p")
		sm.AddOrPanic(ActionHistoryNext, "ctrl+n")
		sm.AddOrPanic(ActionHistoryFirst, "alt+<")
		sm.AddOrPanic(ActionHistoryLast, "alt+>")
		sm.AddOrPanic(ActionHistoryIncrementalSearchBackwards, "ctrl+r")
		sm.AddOrPanic(ActionHistoryIncrementalSearchBackwards, "ctrl+?")
		sm.AddOrPanic(ActionHistoryIncrementalSearchForwards, "ctrl+s")
		sm.AddOrPanic(ActionHistoryIncrementalSearchForwards, "ctrl+/")

		sm.AddOrPanic(ActionNumericArgumentDigit0, "alt+0")
		sm.AddOrPanic(ActionNumericArgumentDigit1, "alt+1")
		sm.AddOrPanic(ActionNumericArgumentDigit2, "alt+2")
		sm.AddOrPanic(ActionNumericArgumentDigit3, "alt+3")
		sm.AddOrPanic(ActionNumericArgumentDigit4, "alt+4")
		sm.AddOrPanic(ActionNumericArgumentDigit5, "alt+5")
		sm.AddOrPanic(ActionNumericArgumentDigit6, "alt+6")
		sm.AddOrPanic(ActionNumericArgumentDigit7, "alt+7")
		sm.AddOrPanic(ActionNumericArgumentDigit8, "alt+8")
		sm.AddOrPanic(ActionNumericArgumentDigit9, "alt+9")
		sm.AddOrPanic(ActionNumericArgumentDigitMinus, "alt+-")

		sm.AddOrPanic(ActionCompleteForward, "Tab")
		sm.AddOrPanic(ActionCompleteBackward, "Shift+Tab")
		_default_shortcuts = sm
	}
	return _default_shortcuts
}

var _history_search_shortcuts *shortcuts.ShortcutMap[Action]

func history_search_shortcuts() *shortcuts.ShortcutMap[Action] {
	if _history_search_shortcuts == nil {
		sm := shortcuts.New[Action]()
		sm.AddOrPanic(ActionBackspace, "backspace")
		sm.AddOrPanic(ActionBackspace, "ctrl+h")

		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "home")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "ctrl+a")

		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "end")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "ctrl+e")

		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "ctrl+home")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "ctrl+end")

		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "alt+f")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "ctrl+right")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "ctrl+left")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "alt+b")

		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "left")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "ctrl+b")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "right")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "ctrl+f")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "up")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "down")

		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "ctrl+c")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "ctrl+g")
		sm.AddOrPanic(ActionTerminateHistorySearchAndRestore, "escape")

		sm.AddOrPanic(ActionTerminateHistorySearchAndApply, "ctrl+d")
		sm.AddOrPanic(ActionTerminateHistorySearchAndApply, "enter")
		sm.AddOrPanic(ActionTerminateHistorySearchAndApply, "ctrl+j")

		_history_search_shortcuts = sm
	}
	return _history_search_shortcuts
}

var ErrCouldNotPerformAction = errors.New("Could not perform the specified action")
var ErrAcceptInput = errors.New("Accept input")

func (self *Readline) push_keyboard_map(m *ShortcutMap) {
	maps := self.keyboard_state.active_shortcut_maps
	self.keyboard_state = KeyboardState{}
	if maps == nil {
		maps = make([]*ShortcutMap, 0, 2)
	}
	self.keyboard_state.active_shortcut_maps = append(maps, m)
}

func (self *Readline) pop_keyboard_map() {
	maps := self.keyboard_state.active_shortcut_maps
	self.keyboard_state = KeyboardState{}
	if len(maps) > 0 {
		maps = maps[:len(maps)-1]
		self.keyboard_state.active_shortcut_maps = maps
	}
}

func (self *Readline) handle_numeric_arg(ac Action) {
	t := "-"
	num := int(ac - ActionNumericArgumentDigit0)
	if num < 10 {
		t = strconv.Itoa(num)
	}
	cna := self.keyboard_state.current_numeric_argument
	if (cna == "" && t == "0") || (cna != "" && t == "-") {
		self.add_text(t)
		self.keyboard_state.current_numeric_argument = ""
		self.last_action = ActionAddText
	} else {
		self.keyboard_state.current_numeric_argument += t
		self.last_action = ac
	}
}

func (self *Readline) dispatch_key_action(ac Action) error {
	self.keyboard_state.current_pending_keys = nil
	if ActionNumericArgumentDigit0 <= ac && ac <= ActionNumericArgumentDigitMinus {
		if self.history_search != nil {
			return ErrCouldNotPerformAction
		}
		self.handle_numeric_arg(ac)
		return nil
	}
	cna := self.keyboard_state.current_numeric_argument
	self.keyboard_state.current_numeric_argument = ""
	if cna == "" {
		cna = "1"
	}
	repeat_count, err := strconv.Atoi(cna)
	if err != nil || repeat_count <= 0 {
		repeat_count = 1
	}
	return self.perform_action(ac, uint(repeat_count))
}

func (self *Readline) handle_key_event(event *loop.KeyEvent) error {
	if event.Text != "" {
		return nil
	}
	sm := default_shortcuts()
	if len(self.keyboard_state.active_shortcut_maps) > 0 {
		sm = self.keyboard_state.active_shortcut_maps[len(self.keyboard_state.active_shortcut_maps)-1]
	}
	ac, pending := sm.ResolveKeyEvent(event, self.keyboard_state.current_pending_keys...)
	if pending != "" {
		event.Handled = true
		if self.keyboard_state.current_pending_keys == nil {
			self.keyboard_state.current_pending_keys = []string{}
		}
		self.keyboard_state.current_pending_keys = append(self.keyboard_state.current_pending_keys, pending)
	} else {
		self.keyboard_state.current_pending_keys = nil
		if ac != ActionNil {
			event.Handled = true
			return self.dispatch_key_action(ac)
		}
	}
	return nil
}
