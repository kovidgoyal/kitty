// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"os"

	"kitty/tools/cli"
	"kitty/tools/config"
	"kitty/tools/tui/loop"
)

var _ = fmt.Print

func load_config(opts *Options) (ans *Config, err error) {
	ans = NewConfig()
	p := config.ConfigParser{LineHandler: ans.Parse}
	err = p.LoadConfig("diff.conf", opts.Config, opts.Override)
	if err != nil {
		return nil, err
	}
	return ans, nil
}

var conf *Config
var opts *Options
var lp *loop.Loop

func isdir(path string) bool {
	if s, err := os.Stat(path); err == nil {
		return s.IsDir()
	}
	return false
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func main(_ *cli.Command, opts_ *Options, args []string) (rc int, err error) {
	opts = opts_
	conf, err = load_config(opts)
	if err != nil {
		return 1, err
	}
	if len(args) != 2 {
		return 1, fmt.Errorf("You must specify exactly two files/directories to compare")
	}
	if err = set_diff_command(conf.Diff_cmd); err != nil {
		return 1, err
	}
	init_caches()
	left, right := get_remote_file(args[0]), get_remote_file(args[1])
	if isdir(left) != isdir(right) {
		return 1, fmt.Errorf("The items to be diffed should both be either directories or files. Comparing a directory to a file is not valid.'")
	}
	if !exists(left) {
		return 1, fmt.Errorf("%s does not exist", left)
	}
	if !exists(right) {
		return 1, fmt.Errorf("%s does not exist", right)
	}
	lp, err = loop.New()
	if err != nil {
		return 1, err
	}
	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		lp.AllowLineWrapping(false)
		lp.SetWindowTitle(fmt.Sprintf("%s vs. %s", left, right))
		return "", nil
	}
	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		return ""
	}
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
