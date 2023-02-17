// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"fmt"
	"strings"
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

func NewEnvInstruction(spec string) (ei *EnvInstruction, err error) {
	const COPY_FROM_LOCAL string = "_kitty_copy_env_var_"
	ei = &EnvInstruction{}
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
	return
}

func NewCopyInstruction(spec string) (ci *CopyInstruction, err error) {
	ci = &CopyInstruction{}
	return
}
