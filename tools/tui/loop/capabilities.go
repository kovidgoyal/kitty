package loop

import (
	"fmt"
)

var _ = fmt.Print

type ColorPreference uint8

const (
	NO_COLOR_PREFERENCE ColorPreference = iota
	DARK_COLOR_PREFERENCE
	LIGHT_COLOR_PREFERENCE
)

func (c ColorPreference) String() string {
	switch c {
	case DARK_COLOR_PREFERENCE:
		return "dark"
	case LIGHT_COLOR_PREFERENCE:
		return "light"
	default:
		return "no-preference"
	}
}

type TerminalCapabilities struct {
	KeyboardProtocol                 bool
	KeyboardProtocolResponseReceived bool

	ColorPreference                 ColorPreference
	ColorPreferenceResponseReceived bool
}
