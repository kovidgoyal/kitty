// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package shell_integration

import (
	"archive/tar"
	"bytes"
	"fmt"
	"kitty/tools/utils"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/exp/maps"
	"golang.org/x/exp/slices"
)

var _ = fmt.Print

type integration_setup_func = func(shell_integration_dir string, argv []string, env map[string]string) ([]string, map[string]string, error)

func extract_shell_integration_for(shell_name string, dest_dir string) (err error) {
	d := Data()
	for _, fname := range d.FilesMatching("shell-integration/" + shell_name + "/") {
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
			if err = utils.AtomicWriteFile(dest, entry.Data, 0o644); err != nil {
				return
			}
		}
	}
	return
}

func EnsureShellIntegrationFilesFor(shell_name string) (shell_integration_dir string, err error) {
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
	return filepath.Join(base, "shell-integration"), nil
}

func zsh_setup_func(shell_integration_dir string, argv []string, env map[string]string) (final_argv []string, final_env map[string]string, err error) {
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

func bash_setup_func(shell_integration_dir string, argv []string, env map[string]string) (final_argv []string, final_env map[string]string, err error) {
	return
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
