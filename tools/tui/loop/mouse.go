// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"strconv"
	"strings"

	"kitty/tools/utils"
)

var _ = fmt.Print

type MouseEventType uint
type MouseButtonFlag uint

const (
	MOUSE_PRESS MouseEventType = iota
	MOUSE_RELEASE
	MOUSE_MOVE
	MOUSE_CLICK
)

func (e MouseEventType) String() string {
	switch e {
	case MOUSE_PRESS:
		return "press"
	case MOUSE_RELEASE:
		return "release"
	case MOUSE_MOVE:
		return "move"
	case MOUSE_CLICK:
		return "click"
	}
	return strconv.Itoa(int(e))
}

const (
	SHIFT_INDICATOR  int = 1 << 2
	ALT_INDICATOR        = 1 << 3
	CTRL_INDICATOR       = 1 << 4
	MOTION_INDICATOR     = 1 << 5
)

const (
	NO_MOUSE_BUTTON   MouseButtonFlag = 0
	LEFT_MOUSE_BUTTON MouseButtonFlag = 1 << iota
	MIDDLE_MOUSE_BUTTON
	RIGHT_MOUSE_BUTTON
	FOURTH_MOUSE_BUTTON
	FIFTH_MOUSE_BUTTON
	SIXTH_MOUSE_BUTTON
	SEVENTH_MOUSE_BUTTON
	MOUSE_WHEEL_UP
	MOUSE_WHEEL_DOWN
	MOUSE_WHEEL_LEFT
	MOUSE_WHEEL_RIGHT
)

var bmap = [...]MouseButtonFlag{LEFT_MOUSE_BUTTON, MIDDLE_MOUSE_BUTTON, RIGHT_MOUSE_BUTTON}
var ebmap = [...]MouseButtonFlag{FOURTH_MOUSE_BUTTON, FIFTH_MOUSE_BUTTON, SIXTH_MOUSE_BUTTON, SEVENTH_MOUSE_BUTTON}
var wbmap = [...]MouseButtonFlag{MOUSE_WHEEL_UP, MOUSE_WHEEL_DOWN, MOUSE_WHEEL_LEFT, MOUSE_WHEEL_RIGHT}

func (b MouseButtonFlag) String() string {
	ans := ""
	switch {
	case b&LEFT_MOUSE_BUTTON != 0:
		ans += "|LEFT"
	case b&MIDDLE_MOUSE_BUTTON != 0:
		ans += "|MIDDLE"
	case b&RIGHT_MOUSE_BUTTON != 0:
		ans += "|RIGHT"
	case b&FOURTH_MOUSE_BUTTON != 0:
		ans += "|FOURTH"
	case b&FIFTH_MOUSE_BUTTON != 0:
		ans += "|FIFTH"
	case b&SIXTH_MOUSE_BUTTON != 0:
		ans += "|SIXTH"
	case b&SEVENTH_MOUSE_BUTTON != 0:
		ans += "|SEVENTH"
	case b&MOUSE_WHEEL_UP != 0:
		ans += "|WHEEL_UP"
	case b&MOUSE_WHEEL_DOWN != 0:
		ans += "|WHEEL_DOWN"
	case b&MOUSE_WHEEL_LEFT != 0:
		ans += "|WHEEL_LEFT"
	case b&MOUSE_WHEEL_RIGHT != 0:
		ans += "|WHEEL_RIGHT"
	}
	ans = strings.TrimLeft(ans, "|")
	if ans == "" {
		ans = "NONE"
	}
	return ans
}

type MouseEvent struct {
	Event_type  MouseEventType
	Buttons     MouseButtonFlag
	Mods        KeyModifiers
	Cell, Pixel struct{ X, Y int }
}

func (e MouseEvent) String() string {
	return fmt.Sprintf("MouseEvent{%s %s %s Cell:%v Pixel:%v}", e.Event_type, e.Buttons, e.Mods, e.Cell, e.Pixel)
}

func pixel_to_cell(px, length, cell_length int) int {
	px = utils.Max(0, utils.Min(px, length-1))
	return px / cell_length
}

func decode_sgr_mouse(text string, screen_size ScreenSize) *MouseEvent {
	last_letter := text[len(text)-1]
	text = text[:len(text)-1]
	parts := strings.Split(text, ";")
	if len(parts) != 3 {
		return nil
	}
	cb, err := strconv.Atoi(parts[0])
	if err != nil {
		return nil
	}
	ans := MouseEvent{}
	ans.Pixel.X, err = strconv.Atoi(parts[1])
	if err != nil {
		return nil
	}
	if len(parts[2]) < 1 {
		return nil
	}
	ans.Pixel.Y, err = strconv.Atoi(parts[2])
	if last_letter == 'm' {
		ans.Event_type = MOUSE_RELEASE
	} else if cb&MOTION_INDICATOR != 0 {
		ans.Event_type = MOUSE_MOVE
	}
	cb3 := cb & 3
	if cb >= 128 {
		ans.Buttons |= ebmap[cb3]
	} else if cb >= 64 {
		ans.Buttons |= wbmap[cb3]
	} else if cb3 < 3 {
		ans.Buttons |= bmap[cb3]
	}
	if cb&SHIFT_INDICATOR != 0 {
		ans.Mods |= SHIFT
	}
	if cb&ALT_INDICATOR != 0 {
		ans.Mods |= ALT
	}
	if cb&CTRL_INDICATOR != 0 {
		ans.Mods |= CTRL
	}
	ans.Cell.X = pixel_to_cell(ans.Pixel.X, int(screen_size.WidthPx), int(screen_size.CellWidth))
	ans.Cell.Y = pixel_to_cell(ans.Pixel.Y, int(screen_size.HeightPx), int(screen_size.CellHeight))

	return &ans
}

func MouseEventFromCSI(csi string, screen_size ScreenSize) *MouseEvent {
	if len(csi) == 0 {
		return nil
	}
	last_char := csi[len(csi)-1]
	if last_char != 'm' && last_char != 'M' {
		return nil
	}
	if !strings.HasPrefix(csi, "<") {
		return nil
	}
	return decode_sgr_mouse(csi[1:], screen_size)
}
