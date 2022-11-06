// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"errors"
	"fmt"
	"strconv"
	"strings"

	"kitty/tools/tui/loop"
)

var _ = fmt.Print

type ShortcutMap struct {
	leaves   map[string]Action
	children map[string]*ShortcutMap
}

type KeyboardState struct {
	shortcut_maps            []*ShortcutMap
	current_pending_keys     []string
	current_numeric_argument string
}

func (self *ShortcutMap) add(ac Action, base string, keys ...string) error {
	items := []string{base}
	items = append(items, keys...)
	sm := self
	for i, key := range items {
		if i == len(items)-1 {
			if sm.children[key] != nil {
				return fmt.Errorf("The shortcut %s conflicts with another multi-key shortcut", strings.Join(items, " > "))
			}
			sm.leaves[key] = ac
		} else {
			if _, found := sm.leaves[key]; found {
				return fmt.Errorf("The shortcut %s conflicts with another multi-key shortcut", strings.Join(items, " > "))
			}
			q := sm.children[key]
			if q == nil {
				q = &ShortcutMap{leaves: map[string]Action{}, children: map[string]*ShortcutMap{}}
				sm.children[key] = q
			}
			sm = q
		}
	}
	return nil
}

var _default_shortcuts *ShortcutMap

func default_shortcuts() *ShortcutMap {
	if _default_shortcuts == nil {
		sm := ShortcutMap{leaves: make(map[string]Action, 32), children: map[string]*ShortcutMap{}}
		sm.add(ActionBackspace, "backspace")
		sm.add(ActionBackspace, "ctrl+h")
		sm.add(ActionDelete, "delete")

		sm.add(ActionMoveToStartOfLine, "home")
		sm.add(ActionMoveToStartOfLine, "ctrl+a")

		sm.add(ActionMoveToEndOfLine, "end")
		sm.add(ActionMoveToEndOfLine, "ctrl+e")

		sm.add(ActionMoveToStartOfDocument, "ctrl+home")
		sm.add(ActionMoveToEndOfDocument, "ctrl+end")

		sm.add(ActionMoveToEndOfWord, "alt+f")
		sm.add(ActionMoveToEndOfWord, "ctrl+right")
		sm.add(ActionMoveToStartOfWord, "ctrl+left")
		sm.add(ActionMoveToStartOfWord, "alt+b")

		sm.add(ActionCursorLeft, "left")
		sm.add(ActionCursorLeft, "ctrl+b")
		sm.add(ActionCursorRight, "right")
		sm.add(ActionCursorRight, "ctrl+f")

		sm.add(ActionClearScreen, "ctrl+l")
		sm.add(ActionAbortCurrentLine, "ctrl+c")

		sm.add(ActionEndInput, "ctrl+d")
		sm.add(ActionAcceptInput, "enter")

		sm.add(ActionKillToEndOfLine, "ctrl+k")
		sm.add(ActionKillToStartOfLine, "ctrl+x")
		sm.add(ActionKillToStartOfLine, "ctrl+u")
		sm.add(ActionKillNextWord, "alt+d")
		sm.add(ActionKillPreviousWord, "alt+backspace")
		sm.add(ActionKillPreviousSpaceDelimitedWord, "ctrl+w")
		sm.add(ActionYank, "ctrl+y")
		sm.add(ActionPopYank, "alt+y")

		sm.add(ActionHistoryPreviousOrCursorUp, "up")
		sm.add(ActionHistoryNextOrCursorDown, "down")
		sm.add(ActionHistoryPrevious, "ctrl+p")
		sm.add(ActionHistoryNext, "ctrl+n")
		sm.add(ActionHistoryFirst, "alt+<")
		sm.add(ActionHistoryLast, "alt+>")

		sm.add(ActionNumericArgumentDigit0, "alt+0")
		sm.add(ActionNumericArgumentDigit1, "alt+1")
		sm.add(ActionNumericArgumentDigit2, "alt+2")
		sm.add(ActionNumericArgumentDigit3, "alt+3")
		sm.add(ActionNumericArgumentDigit4, "alt+4")
		sm.add(ActionNumericArgumentDigit5, "alt+5")
		sm.add(ActionNumericArgumentDigit6, "alt+6")
		sm.add(ActionNumericArgumentDigit7, "alt+7")
		sm.add(ActionNumericArgumentDigit8, "alt+8")
		sm.add(ActionNumericArgumentDigit9, "alt+9")
		sm.add(ActionNumericArgumentDigitMinus, "alt+-")

		_default_shortcuts = &sm
	}
	return _default_shortcuts
}

func (self *Readline) action_for_key_event(event *loop.KeyEvent, shortcuts map[string]Action) Action {
	for sc, ac := range shortcuts {
		if event.MatchesPressOrRepeat(sc) {
			return ac
		}
	}
	return ActionNil
}

var ErrCouldNotPerformAction = errors.New("Could not perform the specified action")
var ErrAcceptInput = errors.New("Accept input")

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
	if len(self.keyboard_state.shortcut_maps) == 0 {
		self.keyboard_state.shortcut_maps = []*ShortcutMap{default_shortcuts()}
	}
	if event.Text != "" {
		return nil
	}
	sm := self.keyboard_state.shortcut_maps[len(self.keyboard_state.shortcut_maps)-1]
	for _, pk := range self.keyboard_state.current_pending_keys {
		sm = sm.children[pk]
	}
	for k := range sm.children {
		if event.MatchesPressOrRepeat(k) {
			event.Handled = true
			if self.keyboard_state.current_pending_keys == nil {
				self.keyboard_state.current_pending_keys = []string{}
			}
			self.keyboard_state.current_pending_keys = append(self.keyboard_state.current_pending_keys, k)
			return nil
		}
	}
	for k, ac := range sm.leaves {
		if event.MatchesPressOrRepeat(k) {
			event.Handled = true
			return self.dispatch_key_action(ac)
		}
	}
	return nil
}
