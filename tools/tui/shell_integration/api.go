// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package shell_integration

import (
	"archive/tar"
	"bytes"
	"fmt"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type integration_setup_func = func(shell_integration_dir string, argv []string, env map[string]string) ([]string, map[string]string, error)

func TerminfoData() string {
	d := Data()
	entry := d["terminfo/x/xterm-kitty"]
	return utils.UnsafeBytesToString(entry.Data)
}

func extract_files(match, dest_dir string) (err error) {
	d := Data()
	for _, fname := range d.FilesMatching(match) {
		entry := d[fname]
		dest := filepath.Join(dest_dir, fname)
		ddir := filepath.Dir(dest)
		if err = os.MkdirAll(ddir, 0o755); err != nil {
			return
		}
		switch entry.Metadata.Typeflag {
		case tar.TypeDir:
			if err = os.MkdirAll(dest, 0o755); err != nil {
				return
			}
		case tar.TypeSymlink:
			if err = os.Symlink(entry.Metadata.Linkname, dest); err != nil {
				return
			}
		case tar.TypeReg:
			if existing, rerr := os.ReadFile(dest); rerr == nil && bytes.Equal(existing, entry.Data) {
				continue
			}
			if err = utils.AtomicWriteFile(dest, bytes.NewReader(entry.Data), 0o644); err != nil {
				return
			}
		}
	}
	return
}

func extract_shell_integration_for(shell_name string, dest_dir string) (err error) {
	return extract_files("shell-integration/"+shell_name+"/", dest_dir)
}

func extract_terminfo(dest_dir string) (err error) {
	var s os.FileInfo
	if s, err = os.Stat(filepath.Join(dest_dir, "terminfo", "x", kitty.DefaultTermName)); err == nil && s.Mode().IsRegular() {
		if s, err = os.Stat(filepath.Join(dest_dir, "terminfo", "78", kitty.DefaultTermName)); err == nil && s.Mode().IsRegular() {
			return
		}
	}
	if err = extract_files("terminfo/", dest_dir); err == nil {
		dest := filepath.Join(dest_dir, "terminfo", "78")
		err = os.Symlink("x", dest)
	}
	return
}

func PathToTerminfoDb(term string) (ans string) {
	// see man terminfo for the algorithm ncurses uses for this

	seen := utils.NewSet[string]()
	check_dir := func(path string) string {
		if seen.Has(path) {
			return ``
		}
		seen.Add(path)
		q := filepath.Join(path, term[:1], term)
		if s, err := os.Stat(q); err == nil && s.Mode().IsRegular() {
			return q
		}
		if entries, err := os.ReadDir(filepath.Join(path)); err == nil {
			for _, x := range entries {
				q := filepath.Join(path, x.Name(), term)
				if s, err := os.Stat(q); err == nil && s.Mode().IsRegular() {
					return q
				}
			}
		}
		return ``
	}

	if td := os.Getenv("TERMINFO"); td != "" {
		if ans = check_dir(td); ans != "" {
			return ans
		}
	}

	if ans = check_dir(utils.Expanduser("~/.terminfo")); ans != "" {
		return ans
	}
	if td := os.Getenv("TERMINFO_DIRS"); td != "" {
		for _, q := range strings.Split(td, string(os.PathListSeparator)) {
			if q == "" {
				q = "/usr/share/terminfo"
			}
			if ans = check_dir(q); ans != "" {
				return ans
			}
		}
	}
	for _, q := range []string{"/usr/share/terminfo", "/usr/lib/terminfo", "/usr/share/lib/terminfo"} {
		if ans = check_dir(q); ans != "" {
			return ans
		}
	}
	return
}

func EnsureTerminfoFiles() (terminfo_dir string, err error) {
	if kid := os.Getenv("KITTY_INSTALLATION_DIR"); kid != "" {
		if s, e := os.Stat(kid); e == nil && s.IsDir() {
			q := filepath.Join(kid, "terminfo")
			if s, e := os.Stat(q); e == nil && s.IsDir() {
				return q, nil
			}
		}
	}
	base := filepath.Join(utils.CacheDir(), "extracted-kti")
	if err = os.MkdirAll(base, 0o755); err != nil {
		return "", err
	}
	if err = extract_terminfo(base); err != nil {
		return "", fmt.Errorf("Failed to extract terminfo files with error: %w", err)
	}
	return filepath.Join(base, "terminfo"), nil
}

func EnsureShellIntegrationFilesFor(shell_name string) (shell_integration_dir_for_shell string, err error) {
	if kid := os.Getenv("KITTY_INSTALLATION_DIR"); kid != "" {
		if s, e := os.Stat(kid); e == nil && s.IsDir() {
			q := filepath.Join(kid, "shell-integration", shell_name)
			if s, e := os.Stat(q); e == nil && s.IsDir() {
				return q, nil
			}
		}
	}
	base := filepath.Join(utils.CacheDir(), "extracted-ksi")
	if err = os.MkdirAll(base, 0o755); err != nil {
		return "", err
	}
	if err = extract_shell_integration_for(shell_name, base); err != nil {
		return "", err
	}
	return filepath.Join(base, "shell-integration", shell_name), nil
}

func is_new_zsh_install(env map[string]string, zdotdir string) bool {
	// if ZDOTDIR is empty, zsh will read user rc files from /
	// if there aren't any, it'll run zsh-newuser-install
	// the latter will bail if there are rc files in $HOME
	if zdotdir == "" {
		if zdotdir = env[`HOME`]; zdotdir == "" {
			if q, err := os.UserHomeDir(); err == nil {
				zdotdir = q
			} else {
				return true
			}
		}
	}
	for _, q := range []string{`.zshrc`, `.zshenv`, `.zprofile`, `.zlogin`} {
		if _, e := os.Stat(filepath.Join(zdotdir, q)); e == nil {
			return false
		}
	}
	return true
}

func get_zsh_zdotdir_from_global_zshenv(argv []string, env map[string]string) string {
	c := exec.Command(utils.FindExe(argv[0]), `--norcs`, `--interactive`, `-c`, `echo -n $ZDOTDIR`)
	for k, v := range env {
		c.Env = append(c.Env, k+"="+v)
	}
	if raw, err := c.Output(); err == nil {
		return utils.UnsafeBytesToString(raw)
	}
	return ""
}

func zsh_setup_func(shell_integration_dir string, argv []string, env map[string]string) (final_argv []string, final_env map[string]string, err error) {
	zdotdir := env[`ZDOTDIR`]
	final_argv, final_env = argv, env
	if is_new_zsh_install(env, zdotdir) {
		if zdotdir == "" {
			// Try to get ZDOTDIR from /etc/zshenv, when all startup files are not present
			zdotdir = get_zsh_zdotdir_from_global_zshenv(argv, env)
			if zdotdir == "" || is_new_zsh_install(env, zdotdir) {
				return final_argv, final_env, nil
			}
		} else {
			// dont prevent zsh-newuser-install from running
			// zsh-newuser-install never runs as root but we assume that it does
			return final_argv, final_env, nil
		}
	}
	if zdotdir != "" {
		env[`KITTY_ORIG_ZDOTDIR`] = zdotdir
	} else {
		// KITTY_ORIG_ZDOTDIR can be set at this point if, for example, the global
		// zshenv overrides ZDOTDIR; we try to limit the damage in this case
		delete(final_env, `KITTY_ORIG_ZDOTDIR`)
	}
	final_env[`ZDOTDIR`] = shell_integration_dir
	return
}

func fish_setup_func(shell_integration_dir string, argv []string, env map[string]string) (final_argv []string, final_env map[string]string, err error) {
	shell_integration_dir = filepath.Dir(shell_integration_dir)
	val := env[`XDG_DATA_DIRS`]
	env[`KITTY_FISH_XDG_DATA_DIR`] = shell_integration_dir
	if val == "" {
		env[`XDG_DATA_DIRS`] = shell_integration_dir
	} else {
		dirs := utils.Filter(strings.Split(val, string(filepath.ListSeparator)), func(x string) bool { return x != "" })
		dirs = append([]string{shell_integration_dir}, dirs...)
		env[`XDG_DATA_DIRS`] = strings.Join(dirs, string(filepath.ListSeparator))
	}
	return argv, env, nil
}

var debugprintln = tty.DebugPrintln
var _ = debugprintln

func bash_setup_func(shell_integration_dir string, argv []string, env map[string]string) ([]string, map[string]string, error) {
	inject := utils.NewSetWithItems(`1`)
	var posix_env, rcfile string
	remove_args := utils.NewSet[int](8)
	expecting_multi_chars_opt := true
	var expecting_option_arg, interactive_opt, expecting_file_arg, file_arg_set bool

	for i := 1; i < len(argv); i++ {
		arg := argv[i]
		if expecting_file_arg {
			file_arg_set = true
			break
		}
		if expecting_option_arg {
			expecting_option_arg = false
			continue
		}
		if arg == `-` || arg == `--` {
			if !expecting_file_arg {
				expecting_file_arg = true
			}
			continue
		} else if len(arg) > 1 && arg[1] != '-' && (arg[0] == '-' || strings.HasPrefix(arg, `+O`)) {
			expecting_multi_chars_opt = false
			options := strings.TrimLeft(arg, `-+`)
			// shopt option
			if a, b, found := strings.Cut(options, `O`); found {
				if b == "" {
					expecting_option_arg = true
				}
				options = a
			}
			// command string
			if strings.ContainsRune(options, 'c') {
				// non-interactive shell
				// also skip `bash -ic` interactive mode with command string
				return argv, env, nil
			}
			// read from stdin and follow with args
			if strings.ContainsRune(options, 's') {
				break
			}
			// interactive option
			if strings.ContainsRune(options, 'i') {
				interactive_opt = true
			}
		} else if strings.HasPrefix(arg, `--`) && expecting_multi_chars_opt {
			if arg == `--posix` {
				inject.Add(`posix`)
				posix_env = env[`ENV`]
				remove_args.Add(i)
			} else if arg == `--norc` {
				inject.Add(`no-rc`)
				remove_args.Add(i)
			} else if arg == `--noprofile` {
				inject.Add(`no-profile`)
				remove_args.Add(i)
			} else if (arg == `--rcfile` || arg == `--init-file`) && i+1 < len(argv) {
				expecting_option_arg = true
				rcfile = argv[i+1]
				remove_args.AddItems(i, i+1)
			}
		} else {
			file_arg_set = true
			break
		}
	}
	if file_arg_set && !interactive_opt {
		// non-interactive shell
		return argv, env, nil
	}
	env[`ENV`] = filepath.Join(shell_integration_dir, `kitty.bash`)
	env[`KITTY_BASH_INJECT`] = strings.Join(inject.AsSlice(), " ")
	if posix_env != "" {
		env[`KITTY_BASH_POSIX_ENV`] = posix_env
	}
	if rcfile != "" {
		env[`KITTY_BASH_RCFILE`] = rcfile
	}
	sorted := remove_args.AsSlice()
	slices.Sort(sorted)
	for _, i := range utils.Reverse(sorted) {
		argv = slices.Delete(argv, i, i+1)
	}
	if env[`HISTFILE`] == "" && !inject.Has(`posix`) {
		// In POSIX mode the default history file is ~/.sh_history instead of ~/.bash_history
		env[`HISTFILE`] = utils.Expanduser(`~/.bash_history`)
		env[`KITTY_BASH_UNEXPORT_HISTFILE`] = `1`
	}
	argv = slices.Insert(argv, 1, `--posix`)

	if bashrc := os.Getenv(`KITTY_RUNNING_BASH_INTEGRATION_TEST`); bashrc != `` && os.Getenv("KITTY_RUNNING_SHELL_INTEGRATION_TEST") == "1" {
		// prevent bash from sourcing /etc/profile which is not under our control
		env[`KITTY_BASH_INJECT`] += ` posix`
		env[`KITTY_BASH_POSIX_ENV`] = bashrc
	}

	return argv, env, nil
}

func setup_func_for_shell(shell_name string) integration_setup_func {
	switch shell_name {
	case "zsh":
		return zsh_setup_func
	case "fish":
		return fish_setup_func
	case "bash":
		return bash_setup_func
	}
	return nil
}

func IsSupportedShell(shell_name string) bool { return setup_func_for_shell(shell_name) != nil }

func Setup(shell_name string, ksi_var string, argv []string, env map[string]string) ([]string, map[string]string, error) {
	ksi_dir, err := EnsureShellIntegrationFilesFor(shell_name)
	if err != nil {
		return nil, nil, err
	}
	argv, env, err = setup_func_for_shell(shell_name)(ksi_dir, slices.Clone(argv), maps.Clone(env))
	if err == nil {
		env[`KITTY_SHELL_INTEGRATION`] = ksi_var
	}
	return argv, env, err
}
