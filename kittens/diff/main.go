// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"archive/tar"
	"bytes"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/kittens/ssh"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func load_config(opts *Options) (ans *Config, err error) {
	ans = NewConfig()
	p := config.ConfigParser{LineHandler: ans.Parse}
	err = p.LoadConfig("diff.conf", opts.Config, opts.Override)
	if err != nil {
		return nil, err
	}
	ans.KeyboardShortcuts = config.ResolveShortcuts(ans.KeyboardShortcuts)
	return ans, nil
}

var conf *Config
var opts *Options
var lp *loop.Loop

var temp_files []string

func resolve_path(path string) (ans string, is_dir bool, err error) {
	var s fs.FileInfo
	if s, err = os.Stat(path); err != nil {
		return
	} else {
		if s.Mode()&fs.ModeNamedPipe != 0 {
			var src, dest *os.File
			if src, err = os.Open(path); err != nil {
				return
			}
			defer src.Close()
			if dest, err = os.CreateTemp("", fmt.Sprintf("*-pipe-%s", filepath.Base(path))); err != nil {
				return
			}
			defer dest.Close()
			temp_files = append(temp_files, dest.Name())
			if _, err = io.Copy(dest, src); err != nil {
				return
			}
			return dest.Name(), false, nil

		} else {
			return path, s.IsDir(), nil
		}
	}
}

func get_ssh_file(hostname, rpath string) (string, error) {
	tdir, err := os.MkdirTemp("", "*-"+hostname)
	if err != nil {
		return "", err
	}
	add_remote_dir(tdir)
	is_abs := strings.HasPrefix(rpath, "/")
	for strings.HasPrefix(rpath, "/") {
		rpath = rpath[1:]
	}
	cmd := []string{ssh.SSHExe(), hostname, "tar", "--dereference", "--create", "--file", "-"}
	if is_abs {
		cmd = append(cmd, "-C", "/")
	}
	cmd = append(cmd, rpath)
	c := exec.Command(cmd[0], cmd[1:]...)
	c.Stdin, c.Stderr = os.Stdin, os.Stderr
	stdout, err := c.Output()
	if err != nil {
		return "", fmt.Errorf("Failed to ssh into remote host %s to get file %s with error: %w", hostname, rpath, err)
	}
	tf := tar.NewReader(bytes.NewReader(stdout))
	count, err := utils.ExtractAllFromTar(tf, tdir)
	if err != nil {
		return "", fmt.Errorf("Failed to untar data from remote host %s to get file %s with error: %w", hostname, rpath, err)
	}
	ans := filepath.Join(tdir, rpath)
	if count == 1 {
		if err = filepath.WalkDir(tdir, func(path string, d fs.DirEntry, err error) error {
			if !d.IsDir() {
				ans = path
				return fs.SkipAll
			}
			return nil
		}); err != nil {
			return "", err
		}
	}
	return ans, nil
}

func get_remote_file(path string) (string, error) {
	if strings.HasPrefix(path, "ssh:") {
		parts := strings.SplitN(path, ":", 3)
		if len(parts) == 3 {
			return get_ssh_file(parts[1], parts[2])
		}
	}
	return path, nil
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
	switch conf.Color_scheme {
	case Color_scheme_light:
		use_light_colors = true
	case Color_scheme_dark:
		use_light_colors = false
	case Color_scheme_auto:
		use_light_colors = false
	}
	init_caches()
	defer func() {
		for tdir := range remote_dirs {
			os.RemoveAll(tdir)
		}
	}()
	left, err := get_remote_file(args[0])
	if err != nil {
		return 1, err
	}
	right, err := get_remote_file(args[1])
	if err != nil {
		return 1, err
	}
	defer func() {
		for _, path := range temp_files {
			os.Remove(path)
		}
	}()
	var left_is_dir, right_is_dir bool
	if left, left_is_dir, err = resolve_path(left); err != nil {
		return 1, err
	}
	if right, right_is_dir, err = resolve_path(right); err != nil {
		return 1, err
	}
	if left_is_dir != right_is_dir {
		return 1, fmt.Errorf("The items to be diffed should both be either directories or files. Comparing a directory to a file is not valid.'")
	}

	lp, err = loop.New()
	loop.MouseTrackingMode(lp, loop.BUTTONS_AND_DRAG_MOUSE_TRACKING)
	if err != nil {
		return 1, err
	}
	lp.ColorSchemeChangeNotifications()
	h := Handler{left: left, right: right, lp: lp}
	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		lp.SetCursorShape(loop.BAR_CURSOR, true)
		lp.AllowLineWrapping(false)
		lp.SetWindowTitle(fmt.Sprintf("%s vs. %s", left, right))
		lp.QueryCapabilities()
		h.initialize()
		return "", nil
	}
	lp.OnCapabilitiesReceived = func(tc loop.TerminalCapabilities) error {
		if !tc.KeyboardProtocol {
			return fmt.Errorf("This terminal does not support the kitty keyboard protocol, or you are running inside a terminal multiplexer that is blocking querying for kitty keyboard protocol support. The diff kitten cannot function without it.")
		}
		h.on_capabilities_received(tc)
		return nil
	}
	lp.OnWakeup = h.on_wakeup
	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		lp.SetCursorShape(loop.BLOCK_CURSOR, true)
		h.finalize()
		return ""
	}
	lp.OnResize = h.on_resize
	lp.OnKeyEvent = h.on_key_event
	lp.OnText = h.on_text
	lp.OnMouseEvent = h.on_mouse_event
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
