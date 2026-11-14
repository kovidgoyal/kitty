// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"fmt"
	"strings"

	"github.com/kovidgoyal/datty"
	"github.com/kovidgoyal/datty/tools/cli"
	"github.com/kovidgoyal/datty/tools/utils"
)

var _ = fmt.Print

func complete_actions(completions *cli.Completions, word string, arg_num int) {
	if arg_num < 2 {
		scanner := utils.NewLineScanner(DattyActionNames)
		mg := completions.AddMatchGroup("Actions")
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line != "" && strings.HasPrefix(line, word) {
				mg.AddMatch(line)
			}
		}
	}
}

func complete_datty_override(completions *cli.Completions, word string, arg_num int) {
	mg := completions.AddMatchGroup("Config directives")
	mg.NoTrailingSpace = true
	scanner := utils.NewLineScanner(datty.OptionNames)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, word) {
			mg.AddMatch(line + "=")
		}
	}
}
