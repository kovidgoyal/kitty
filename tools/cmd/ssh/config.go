// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"fmt"
)

var _ = fmt.Print

type EnvInstruction struct {
}

type CopyInstruction struct {
}

func NewEnvInstruction(spec string) (ei *EnvInstruction, err error) {
	return
}

func NewCopyInstruction(spec string) (ci *CopyInstruction, err error) {
	return
}
