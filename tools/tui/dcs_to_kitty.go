// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"encoding/base64"
	"fmt"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func DCSToKitty(msgtype, payload string) (string, error) {
	data := base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(payload))
	ans := "\x1bP@kitty-" + msgtype + "|" + data
	tmux := TmuxSocketAddress()
	if tmux != "" {
		err := TmuxAllowPassthrough()
		if err != nil {
			return "", err
		}
		ans = "\033Ptmux;\033" + ans + "\033\033\\\033\\"
	} else {
		ans += "\033\\"
	}
	return ans, nil
}
