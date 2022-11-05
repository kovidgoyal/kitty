// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"errors"
	"fmt"

	"kitty/tools/tui/loop"
)

var _ = fmt.Print

var default_shortcuts = map[string]Action{
	"backspace": ActionBackspace,
	"ctrl+h":    ActionBackspace,
	"delete":    ActionDelete,

	"home":   ActionMoveToStartOfLine,
	"ctrl+a": ActionMoveToStartOfLine,

	"end":    ActionMoveToEndOfLine,
	"ctrl+e": ActionMoveToEndOfLine,

	"ctrl+home": ActionMoveToStartOfDocument,
	"ctrl+end":  ActionMoveToEndOfDocument,

	"alt+f":      ActionMoveToEndOfWord,
	"ctrl+right": ActionMoveToEndOfWord,
	"ctrl+left":  ActionMoveToStartOfWord,
	"alt+b":      ActionMoveToStartOfWord,

	"left":   ActionCursorLeft,
	"ctrl+b": ActionCursorLeft,
	"right":  ActionCursorRight,
	"ctrl+f": ActionCursorRight,

	"ctrl+l": ActionClearScreen,

	"ctrl+d": ActionEndInput,
	"enter":  ActionAcceptInput,

	"ctrl+k":        ActionKillToEndOfLine,
	"ctrl+x":        ActionKillToStartOfLine,
	"ctrl+u":        ActionKillToStartOfLine,
	"alt+d":         ActionKillNextWord,
	"alt+backspace": ActionKillPreviousWord,
	"ctrl+w":        ActionKillPreviousSpaceDelimitedWord,
	"ctrl+y":        ActionYank,
	"alt+y":         ActionPopYank,

	"up":     ActionHistoryPreviousOrCursorUp,
	"down":   ActionHistoryNextOrCursorDown,
	"ctrl+p": ActionHistoryPrevious,
	"ctrl+n": ActionHistoryNext,
	"alt+<":  ActionHistoryFirst,
	"alt+>":  ActionHistoryLast,

	"ctrl+c": ActionAbortCurrentLine,
}

func action_for_key_event(event *loop.KeyEvent, shortcuts map[string]Action) Action {
	for sc, ac := range shortcuts {
		if event.MatchesPressOrRepeat(sc) {
			return ac
		}
	}
	return ActionNil
}

var ErrCouldNotPerformAction = errors.New("Could not perform the specified action")
var ErrAcceptInput = errors.New("Accept input")

func (self *Readline) handle_key_event(event *loop.KeyEvent) error {
	if event.Text != "" {
		return nil
	}
	ac := action_for_key_event(event, default_shortcuts)
	if ac != ActionNil {
		event.Handled = true
		return self.perform_action(ac, 1)
	}
	return nil
}
