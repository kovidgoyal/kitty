// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/themes"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
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
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	cv := utils.NewCachedValues("unicode-input", &CachedData{Category: "All"})
	h := &handler{lp: lp, opts: opts, cached_data: cv.Load()}
	defer cv.Save()
	lp.OnInitialize = func() (string, error) {
		lp.AllowLineWrapping(false)
		lp.SetWindowTitle(`Choose a theme for kitty`)
		h.initialize()
		return "", nil
	}
	lp.OnWakeup = h.on_wakeup
	lp.OnFinalize = func() string {
		h.finalize()
		lp.SetCursorVisible(true)
		return ``
	}
	lp.OnResize = func(_, _ loop.ScreenSize) error {
		h.draw_screen()
		return nil
	}
	lp.OnKeyEvent = h.on_key_event
	lp.OnText = h.on_text
	err = lp.Run()
	if err != nil {
		return 1, err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return 1, nil
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}

func parse_theme_metadata() error {
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		return err
	}
	paths := utils.Splitlines(utils.UnsafeBytesToString(raw))
	ans := make([]*themes.ThemeMetadata, 0, len(paths))
	for _, path := range paths {
		if path != "" {
			metadata, _, err := themes.ParseThemeMetadata(path)
			if err != nil {
				return err
			}
			if metadata.Name == "" {
				metadata.Name = themes.ThemeNameFromFileName(filepath.Base(path))
			}
			ans = append(ans, metadata)
		}
	}
	raw, err = json.Marshal(ans)
	if err != nil {
		return err
	}
	_, err = os.Stdout.Write(raw)
	if err != nil {
		return err
	}
	return nil
}

func ParseEntryPoint(parent *cli.Command) {
	parent.AddSubCommand(&cli.Command{
		Name:   "__parse_theme_metadata__",
		Hidden: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			err = parse_theme_metadata()
			if err != nil {
				rc = 1
			}
			return
		},
	})

}
