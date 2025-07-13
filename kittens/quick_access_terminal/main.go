package quick_access_terminal

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"github.com/kovidgoyal/kitty/kittens/panel"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/utils"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

var complete_kitty_listen_on = panel.CompleteKittyListenOn

func load_config(opts *Options) (ans *Config, err error) {
	ans = NewConfig()
	p := config.ConfigParser{LineHandler: ans.Parse}
	err = p.LoadConfig("quick-access-terminal.conf", opts.Config, opts.Override)
	if err != nil {
		return nil, err
	}
	return ans, nil
}

func main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	conf, err := load_config(opts)
	if err != nil {
		return 1, err
	}
	kitty_exe, err := panel.GetQuickAccessKittyExe()
	if err != nil {
		return 1, err
	}
	argv := []string{kitty_exe, "+kitten", "panel", "--toggle-visibility", "--exclusive-zone=0", "--override-exclusive-zone", "--layer=overlay", "--single-instance"}
	argv = append(argv, fmt.Sprintf("--lines=%s", conf.Lines))
	argv = append(argv, fmt.Sprintf("--columns=%s", conf.Columns))
	argv = append(argv, fmt.Sprintf("--edge=%s", conf.Edge))
	if conf.Margin_top != 0 {
		argv = append(argv, fmt.Sprintf("--margin-top=%d", conf.Margin_top))
	}
	if conf.Margin_bottom != 0 {
		argv = append(argv, fmt.Sprintf("--margin-bottom=%d", conf.Margin_bottom))
	}
	if conf.Margin_left != 0 {
		argv = append(argv, fmt.Sprintf("--margin-left=%d", conf.Margin_left))
	}
	if conf.Margin_right != 0 {
		argv = append(argv, fmt.Sprintf("--margin-right=%d", conf.Margin_right))
	}
	if len(conf.Kitty_conf) > 0 {
		cdir := utils.ConfigDir()
		for _, c := range conf.Kitty_conf {
			if !filepath.IsAbs(c) {
				c = filepath.Join(cdir, c)
			}
			argv = append(argv, fmt.Sprintf("--config=%s", c))
		}
	}
	if len(conf.Kitty_override) > 0 {
		for _, c := range conf.Kitty_override {
			argv = append(argv, fmt.Sprintf("--override=%s", c))
		}
	}

	argv = append(argv, fmt.Sprintf("--override=background_opacity=%f", conf.Background_opacity))
	if runtime.GOOS != "darwin" {
		argv = append(argv, fmt.Sprintf("--app-id=%s", conf.App_id))
	}
	if conf.Output_name != "" {
		argv = append(argv, fmt.Sprintf("--output-name=%s", conf.Output_name))
	}
	argv = append(argv, fmt.Sprintf("--focus-policy=%s", conf.Focus_policy))
	if conf.Start_as_hidden {
		argv = append(argv, `--start-as-hidden`)
	}
	if conf.Grab_keyboard {
		argv = append(argv, `--grab-keyboard`)
	}
	if conf.Hide_on_focus_loss {
		argv = append(argv, `--hide-on-focus-loss`)
	}
	if opts.DebugRendering {
		argv = append(argv, `--debug-rendering`)
	}
	if opts.DebugInput {
		argv = append(argv, `--debug-input`)
	}
	if opts.Detach {
		argv = append(argv, `--detach`)
	}
	if opts.DetachedLog != "" {
		if dl, err := filepath.Abs(opts.DetachedLog); err != nil {
			return 1, err
		} else {
			argv = append(argv, dl)
		}
	}
	if opts.InstanceGroup != "" {
		argv = append(argv, fmt.Sprintf("--instance-group=%s", opts.InstanceGroup))
	}

	argv = append(argv, args...)
	err = unix.Exec(kitty_exe, argv, os.Environ())
	rc = 1
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
