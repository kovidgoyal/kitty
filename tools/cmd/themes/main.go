// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"fmt"
	"strings"
	"time"

	"kitty/tools/cli"
	"kitty/tools/themes"
	"kitty/tools/utils"
)

var _ = fmt.Print

func complete_themes(completions *cli.Completions, word string, arg_num int) {
	themes.CompleteThemes(completions, word, arg_num)
}

func non_interactive(opts *Options, theme_name string) (rc int, err error) {
	themes, closer, err := themes.LoadThemes(time.Duration(opts.CacheAge * float64(time.Hour*24)))
	if err != nil {
		return 1, err
	}
	defer closer.Close()
	theme := themes.ThemeByName(theme_name)
	if theme == nil {
		theme_name = strings.ReplaceAll(theme_name, `\`, ``)
		theme = themes.ThemeByName(theme_name)
		if theme == nil {
			return 1, fmt.Errorf("No theme named: %s", theme_name)
		}
	}
	if opts.DumpTheme {
		code, err := theme.Code()
		if err != nil {
			return 1, err
		}
		fmt.Println(code)
	} else {
		err = theme.SaveInConf(utils.ConfigDir(), opts.ReloadIn, opts.ConfigFileName)
		if err != nil {
			return 1, err
		}
	}
	return
}

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	if len(args) > 1 {
		args = []string{strings.Join(args, ` `)}
	}
	if len(args) == 1 {
		return non_interactive(opts, args[0])
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
