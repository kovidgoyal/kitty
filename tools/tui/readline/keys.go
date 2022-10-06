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
	"delete":    ActionDelete,
	"home":      ActionMoveToStartOfLine,
	"end":       ActionMoveToEndOfLine,
	"ctrl+home": ActionMoveToStartOfDocument,
	"ctrl+end":  ActionMoveToEndOfDocument,
	"left":      ActionCursorLeft,
	"right":     ActionCursorRight,
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

func (self *Readline) handle_key_event(event *loop.KeyEvent) error {
	if event.Text != "" {
		return nil
	}
	ac := action_for_key_event(event, default_shortcuts)
	if ac != ActionNil {
		event.Handled = true
		if !self.perform_action(ac, 1) {
			return ErrCouldNotPerformAction
		}
	}
	return nil
}
