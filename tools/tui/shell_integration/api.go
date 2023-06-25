// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package shell_integration

import (
	"archive/tar"
	"fmt"
	"os"
	"path/filepath"
)

var _ = fmt.Print

type integration_setup_func = func(argv []string, env map[string]string) ([]string, map[string]string, error)

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
			if err = os.WriteFile(dest, entry.Data, 0o644); err != nil {
				return
			}
		}
	}
	return
}

func zsh_setup_func(argv []string, env map[string]string) (final_argv []string, final_env map[string]string, err error) {
	return
}

func fish_setup_func(argv []string, env map[string]string) (final_argv []string, final_env map[string]string, err error) {
	return
}

func bash_setup_func(argv []string, env map[string]string) (final_argv []string, final_env map[string]string, err error) {
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

func Setup(shell_name string, argv []string, env map[string]string) ([]string, map[string]string, error) {
	return setup_func_for_shell(shell_name)(argv, env)
}
