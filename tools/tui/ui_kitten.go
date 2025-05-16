// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"encoding/json"
	"fmt"
	"os"
	"sync"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/base85"
)

var _ = fmt.Print

var RunningAsUI = sync.OnceValue(func() bool {
	defer func() { os.Unsetenv("KITTEN_RUNNING_AS_UI") }()
	return os.Getenv("KITTEN_RUNNING_AS_UI") != ""
})

type BasicColors struct {
	Foreground uint32 `json:"foreground"`
	Background uint32 `json:"background"`
	Color0     uint32 `json:"color0"`
	Color1     uint32 `json:"color1"`
	Color2     uint32 `json:"color2"`
	Color3     uint32 `json:"color3"`
	Color4     uint32 `json:"color4"`
	Color5     uint32 `json:"color5"`
	Color6     uint32 `json:"color6"`
	Color7     uint32 `json:"color7"`
	Color8     uint32 `json:"color8"`
	Color9     uint32 `json:"color9"`
	Color10    uint32 `json:"color10"`
	Color11    uint32 `json:"color11"`
	Color12    uint32 `json:"color12"`
	Color13    uint32 `json:"color13"`
	Color14    uint32 `json:"color14"`
	Color15    uint32 `json:"color15"`
}

func ReadBasicColors() (ans BasicColors, err error) {
	q := os.Getenv("KITTY_BASIC_COLORS")
	if q == "" {
		err = fmt.Errorf("No KITTY_BASIC_COLORS env var")
	} else {
		err = json.Unmarshal(utils.UnsafeStringToBytes(q), &ans)
	}
	return
}

func PrepareRootCmd(root *cli.Command) {
	if RunningAsUI() {
		root.CallbackOnError = func(cmd *cli.Command, err error, during_parsing bool, exit_code int) int {
			cli.ShowError(err)
			os.Stdout.WriteString("\x1bP@kitty-overlay-ready|\x1b\\")
			HoldTillEnter(true)
			return exit_code
		}
	}
}

func KittenOutputSerializer() func(any) (string, error) {
	if RunningAsUI() {
		return func(what any) (string, error) {
			data, err := json.Marshal(what)
			if err != nil {
				return "", err
			}
			return "\x1bP@kitty-kitten-result|" + base85.EncodeToString(data) + "\x1b\\", nil
		}
	}
	return func(what any) (string, error) {
		if sval, ok := what.(string); ok {
			return sval, nil
		}
		data, err := json.MarshalIndent(what, "", "  ")
		if err != nil {
			return "", err
		}
		return utils.UnsafeBytesToString(data), nil
	}
}
