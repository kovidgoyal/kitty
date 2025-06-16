// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty"
)

type KeyboardStateBits uint8

const (
	LEGACY_KEYS                     KeyboardStateBits = 0
	DISAMBIGUATE_KEYS                                 = 1
	REPORT_KEY_EVENT_TYPES                            = 2
	REPORT_ALTERNATE_KEYS                             = 4
	REPORT_ALL_KEYS_AS_ESCAPE_CODES                   = 8
	REPORT_TEXT_WITH_KEYS                             = 16
	FULL_KEYBOARD_PROTOCOL                            = DISAMBIGUATE_KEYS | REPORT_ALTERNATE_KEYS | REPORT_ALL_KEYS_AS_ESCAPE_CODES | REPORT_TEXT_WITH_KEYS | REPORT_KEY_EVENT_TYPES
	NO_KEYBOARD_STATE_CHANGE                          = 32
)

const (
	SAVE_CURSOR                   = "\0337"
	RESTORE_CURSOR                = "\0338"
	SAVE_PRIVATE_MODE_VALUES      = "\033[?s"
	RESTORE_PRIVATE_MODE_VALUES   = "\033[?r"
	SAVE_COLORS                   = "\033[#P"
	RESTORE_COLORS                = "\033[#Q"
	DECSACE_DEFAULT_REGION_SELECT = "\033[*x"
	CLEAR_SCREEN                  = "\033[H\033[2J"
)

type CursorShapes uint

const (
	BLOCK_CURSOR     CursorShapes = 1
	UNDERLINE_CURSOR CursorShapes = 3
	BAR_CURSOR       CursorShapes = 5
)

type Mode uint32

const private Mode = 1 << 31

const (
	LNM                              Mode = 20
	IRM                              Mode = 4
	DECKM                            Mode = 1 | private
	DECSCNM                          Mode = 5 | private
	DECOM                            Mode = 6 | private
	DECAWM                           Mode = 7 | private
	DECARM                           Mode = 8 | private
	DECTCEM                          Mode = 25 | private
	MOUSE_BUTTON_TRACKING            Mode = 1000 | private
	MOUSE_MOTION_TRACKING            Mode = 1002 | private
	MOUSE_MOVE_TRACKING              Mode = 1003 | private
	FOCUS_TRACKING                   Mode = 1004 | private
	MOUSE_UTF8_MODE                  Mode = 1005 | private
	MOUSE_SGR_MODE                   Mode = 1006 | private
	MOUSE_URXVT_MODE                 Mode = 1015 | private
	MOUSE_SGR_PIXEL_MODE             Mode = 1016 | private
	ALTERNATE_SCREEN                 Mode = 1049 | private
	BRACKETED_PASTE                  Mode = 2004 | private
	PENDING_UPDATE                   Mode = 2026 | private
	COLOR_SCHEME_CHANGE_NOTIFICATION Mode = 2031 | private
	INBAND_RESIZE_NOTIFICATION       Mode = 2048 | private
	HANDLE_TERMIOS_SIGNALS           Mode = kitty.HandleTermiosSignals | private
)

func (self Mode) escape_code(which string) string {
	num := self
	priv := ""
	if num&private > 0 {
		priv = "?"
		num &^= private
	}
	return fmt.Sprintf("\033[%s%d%s", priv, uint32(num), which)
}

func (self Mode) EscapeCodeToSet() string {
	return self.escape_code("h")
}

func (self Mode) EscapeCodeToReset() string {
	return self.escape_code("l")
}

type MouseTracking uint8

const (
	NO_MOUSE_TRACKING MouseTracking = iota
	BUTTONS_ONLY_MOUSE_TRACKING
	BUTTONS_AND_DRAG_MOUSE_TRACKING
	FULL_MOUSE_TRACKING
)

type TerminalStateOptions struct {
	Alternate_screen, restore_colors bool
	mouse_tracking                   MouseTracking
	kitty_keyboard_mode              KeyboardStateBits
	in_band_resize_notification      bool
	focus_tracking                   bool
	color_scheme_change_notification bool
}

func set_modes(sb *strings.Builder, modes ...Mode) {
	for _, m := range modes {
		sb.WriteString(m.EscapeCodeToSet())
	}
}

func reset_modes(sb *strings.Builder, modes ...Mode) {
	for _, m := range modes {
		sb.WriteString(m.EscapeCodeToReset())
	}
}

func (self *TerminalStateOptions) SetStateEscapeCodes() string {
	var sb strings.Builder
	sb.Grow(256)
	if self.Alternate_screen {
		sb.WriteString(SAVE_CURSOR)
	}
	sb.WriteString(SAVE_PRIVATE_MODE_VALUES)
	if self.restore_colors {
		sb.WriteString(SAVE_COLORS)
	}
	sb.WriteString(DECSACE_DEFAULT_REGION_SELECT)
	reset_modes(&sb,
		IRM, DECKM, DECSCNM, BRACKETED_PASTE,
		MOUSE_BUTTON_TRACKING, MOUSE_MOTION_TRACKING, MOUSE_MOVE_TRACKING, MOUSE_UTF8_MODE, MOUSE_SGR_MODE)
	set_modes(&sb, DECARM, DECAWM, DECTCEM)
	if self.focus_tracking {
		set_modes(&sb, FOCUS_TRACKING)
	}
	if self.in_band_resize_notification {
		set_modes(&sb, INBAND_RESIZE_NOTIFICATION)
	}
	if self.color_scheme_change_notification {
		set_modes(&sb, COLOR_SCHEME_CHANGE_NOTIFICATION)
	}
	if self.Alternate_screen {
		set_modes(&sb, ALTERNATE_SCREEN)
		sb.WriteString(CLEAR_SCREEN)
	}
	switch self.kitty_keyboard_mode {
	case LEGACY_KEYS:
		sb.WriteString("\033[>u")
	case NO_KEYBOARD_STATE_CHANGE:
	default:
		sb.WriteString(fmt.Sprintf("\033[>%du", self.kitty_keyboard_mode))
	}
	if self.mouse_tracking != NO_MOUSE_TRACKING {
		sb.WriteString(MOUSE_SGR_PIXEL_MODE.EscapeCodeToSet())
		switch self.mouse_tracking {
		case BUTTONS_ONLY_MOUSE_TRACKING:
			sb.WriteString(MOUSE_BUTTON_TRACKING.EscapeCodeToSet())
		case BUTTONS_AND_DRAG_MOUSE_TRACKING:
			sb.WriteString(MOUSE_MOTION_TRACKING.EscapeCodeToSet())
		case FULL_MOUSE_TRACKING:
			sb.WriteString(MOUSE_MOVE_TRACKING.EscapeCodeToSet())
		}
	}
	return sb.String()
}

func (self *TerminalStateOptions) ResetStateEscapeCodes() string {
	var sb strings.Builder
	sb.Grow(64)
	if self.kitty_keyboard_mode != NO_KEYBOARD_STATE_CHANGE {
		sb.WriteString("\033[<u")
	}
	if self.Alternate_screen {
		sb.WriteString(ALTERNATE_SCREEN.EscapeCodeToReset())
	} else {
		sb.WriteString(SAVE_CURSOR)
	}
	// Explictly turn off this mode as there are some terminals that dont
	// support restoring all modes and people tend to use the show-key kitten
	// in other terminals. Since I do want to encourage adoption of the kitty
	// keyboard protocol, the extra bytes are worth it in this case.
	if self.in_band_resize_notification {
		reset_modes(&sb, INBAND_RESIZE_NOTIFICATION)
	}
	sb.WriteString(RESTORE_PRIVATE_MODE_VALUES)
	if self.restore_colors {
		sb.WriteString(RESTORE_COLORS)
	}
	sb.WriteString(RESTORE_CURSOR)
	return sb.String()
}

func CursorShape(shape CursorShapes, blink bool) string {
	if !blink {
		shape += 1
	}
	return fmt.Sprintf("\x1b[%d q", shape)
}
