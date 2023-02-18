// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"kitty/tools/utils/paths"
	"kitty/tools/utils/shlex"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

type EnvInstruction struct {
	key, val                          string
	delete_on_remote, copy_from_local bool
}

type CopyInstruction struct {
	local_path, arcname string
	exclude_patterns    []string
}

func ParseEnvInstruction(spec string) (ans []*EnvInstruction, err error) {
	const COPY_FROM_LOCAL string = "_kitty_copy_env_var_"
	ei := &EnvInstruction{}
	found := false
	ei.key, ei.val, found = strings.Cut(spec, "=")
	ei.key = strings.TrimSpace(ei.key)
	if found {
		ei.val = strings.TrimSpace(ei.val)
		if ei.val == COPY_FROM_LOCAL {
			ei.val = ""
			ei.copy_from_local = true
		}
	} else {
		ei.delete_on_remote = true
	}
	if ei.key == "" {
		err = fmt.Errorf("The env directive must not be empty")
	}
	ans = []*EnvInstruction{ei}
	return
}

var paths_ctx *paths.Ctx

func resolve_file_spec(spec string, is_glob bool) ([]string, error) {
	if paths_ctx == nil {
		paths_ctx = &paths.Ctx{}
	}
	ans := os.ExpandEnv(paths_ctx.ExpandHome(spec))
	if !filepath.IsAbs(ans) {
		ans = paths_ctx.AbspathFromHome(ans)
	}
	if is_glob {
		files, err := filepath.Glob(ans)
		if err != nil {
			return nil, err
		}
		if len(files) == 0 {
			return nil, fmt.Errorf("%s does not exist", spec)
		}
		return files, nil
	}
	err := unix.Access(ans, unix.R_OK)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("%s does not exist", spec)
		}
		return nil, fmt.Errorf("Cannot read from: %s with error: %w", spec, err)
	}
	return []string{ans}, nil
}

func get_arcname(loc, dest, home string) (arcname string) {
	if dest != "" {
		arcname = dest
	} else {
		arcname = filepath.Clean(loc)
		if filepath.HasPrefix(arcname, home) {
			ra, err := filepath.Rel(home, arcname)
			if err == nil {
				arcname = ra
			}
		}
	}
	prefix := "home/"
	if strings.HasPrefix(arcname, "/") {
		prefix = "root"
	}
	return prefix + arcname
}

func ParseCopyInstruction(spec string) (ans []*CopyInstruction, err error) {
	args, err := shlex.Split(spec)
	if err != nil {
		return nil, err
	}
	opts, args, err := parse_copy_args(args)
	if err != nil {
		return nil, err
	}
	locations := make([]string, 0, len(args))
	for _, arg := range args {
		locs, err := resolve_file_spec(arg, opts.Glob)
		if err != nil {
			return nil, err
		}
		locations = append(locations, locs...)
	}
	if len(locations) == 0 {
		return nil, fmt.Errorf("No files to copy specified")
	}
	if len(locations) > 1 && opts.Dest != "" {
		return nil, fmt.Errorf("Specifying a remote location with more than one file is not supported")
	}
	home := paths_ctx.HomePath()
	ans = make([]*CopyInstruction, 0, len(locations))
	for _, loc := range locations {
		ci := CopyInstruction{local_path: loc, exclude_patterns: opts.Exclude}
		if opts.SymlinkStrategy != "preserve" {
			ci.local_path, err = filepath.EvalSymlinks(loc)
			if err != nil {
				return nil, fmt.Errorf("Failed to resolve symlinks in %#v with error: %w", loc, err)
			}
		}
		if opts.SymlinkStrategy == "resolve" {
			ci.arcname = get_arcname(ci.local_path, opts.Dest, home)
		} else {
			ci.arcname = get_arcname(loc, opts.Dest, home)
		}
		ans = append(ans, &ci)
	}
	return
}
