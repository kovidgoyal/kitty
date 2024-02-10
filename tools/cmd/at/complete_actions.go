// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"fmt"
	"strings"

	"kitty/tools/cli"
	"kitty/tools/utils"
)

var _ = fmt.Print

func complete_actions(completions *cli.Completions, word string, arg_num int) {
	if arg_num < 2 {
		scanner := utils.NewLineScanner(KittyActionNames)
		mg := completions.AddMatchGroup("Actions")
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line != "" && strings.HasPrefix(line, word) {
				mg.AddMatch(line)
			}
		}
	}
}
