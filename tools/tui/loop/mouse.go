// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"strconv"
	"strings"

	"kitty/tools/utils"
)

var _ = fmt.Print

type MouseEventType int
type MouseButtonFlag int

const (
	MOUSE_PRESS MouseEventType = iota
	MOUSE_RELEASE
	MOUSE_MOVE
)
const (
	SHIFT_INDICATOR  int = 1 << 2
	ALT_INDICATOR        = 1 << 3
	CTRL_INDICATOR       = 1 << 4
	MOTION_INDICATOR     = 1 << 5
)

const NONE, LEFT, MIDDLE, RIGHT, FOURTH, FIFTH, SIXTH, SEVENTH MouseButtonFlag = 0, 1, 2, 4, 8, 16, 32, 64
const WHEEL_UP, WHEEL_DOWN, WHEEL_LEFT, WHEEL_RIGHT MouseButtonFlag = -1, -2, -4, -8

var bmap = [...]MouseButtonFlag{LEFT, MIDDLE, RIGHT}
var ebmap = [...]MouseButtonFlag{FOURTH, FIFTH, SIXTH, SEVENTH}
var wbmap = [...]MouseButtonFlag{WHEEL_UP, WHEEL_DOWN, WHEEL_LEFT, WHEEL_RIGHT}

type MouseEvent struct {
	Event_type  MouseEventType
	Buttons     MouseButtonFlag
	Mods        KeyModifiers
	Cell, Pixel struct{ x, y int }
}

func pixel_to_cell(px, length, cell_length int) int {
	px = utils.Max(0, utils.Min(px, length-1))
	return px / cell_length
}

func decode_sgr_mouse(text string, screen_size ScreenSize) *MouseEvent {
	parts := strings.Split(text, ";")
	if len(parts) != 3 {
		return nil
	}
	cb, err := strconv.Atoi(parts[0])
	if err != nil {
		return nil
	}
	ans := MouseEvent{}
	ans.Pixel.x, err = strconv.Atoi(parts[1])
	if err != nil {
		return nil
	}
	if len(parts[2]) < 1 {
		return nil
	}
	ans.Pixel.y, err = strconv.Atoi(parts[2][:len(parts[2])-1])
	m := parts[2][len(parts[2])-1]
	if m == 'm' {
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
	ans.Cell.x = pixel_to_cell(ans.Pixel.x, int(screen_size.WidthPx), int(screen_size.CellWidth))
	ans.Cell.y = pixel_to_cell(ans.Pixel.y, int(screen_size.HeightPx), int(screen_size.CellHeight))

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
	csi = csi[:len(csi)-1]
	if !strings.HasPrefix(csi, "<") {
		return nil
	}
	return decode_sgr_mouse(csi[1:], screen_size)
}
