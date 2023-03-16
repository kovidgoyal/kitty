// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"bytes"
	"errors"
	"fmt"
	"kitty/tools/utils"
	"kitty/tools/utils/shlex"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
)

var _ = fmt.Print

const GIT_DIFF = `git diff --no-color --no-ext-diff --exit-code -U_CONTEXT_ --no-index --`
const DIFF_DIFF = `diff -p -U _CONTEXT_ --`

var diff_cmd []string

var GitExe = (&utils.Once[string]{Run: func() string {
	return utils.FindExe("git")
}}).Get

var DiffExe = (&utils.Once[string]{Run: func() string {
	return utils.FindExe("diff")
}}).Get

func find_differ() error {
	if GitExe() != "git" && exec.Command(GitExe(), "--help").Run() == nil {
		diff_cmd, _ = shlex.Split(GIT_DIFF)
		return nil
	}
	if DiffExe() != "diff" && exec.Command(DiffExe(), "--help").Run() == nil {
		diff_cmd, _ = shlex.Split(DIFF_DIFF)
		return nil
	}
	return fmt.Errorf("Neither the git nor the diff programs were found in PATH")
}

func set_diff_command(q string) error {
	if q == "auto" {
		return find_differ()
	}
	c, err := shlex.Split(q)
	if err == nil {
		diff_cmd = c
	}
	return err
}

func run_diff(file1, file2 string, num_of_context_lines int) (ok, is_different bool, patch string, err error) {
	context := strconv.Itoa(num_of_context_lines)
	cmd := utils.Map(func(x string) string {
		return strings.ReplaceAll(x, "_CONTEXT_", context)
	}, diff_cmd)
	// we resolve symlinks because git diff does not follow symlinks, while diff
	// does. We want consistent behavior, also for integration with git difftool
	// we always want symlinks to be followed.
	path1, err := filepath.EvalSymlinks(file1)
	if err != nil {
		return
	}
	path2, err := filepath.EvalSymlinks(file2)
	if err != nil {
		return
	}
	cmd = append(cmd, path1, path2)
	c := exec.Command(cmd[0], cmd[1:]...)
	stdout, stderr := bytes.Buffer{}, bytes.Buffer{}
	c.Stdout, c.Stderr = &stdout, &stderr
	err = c.Run()
	if err != nil {
		var e *exec.ExitError
		if errors.As(err, &e) && e.ExitCode() == 1 {
			return true, true, stdout.String(), nil
		}
		return false, false, stderr.String(), err
	}
	return true, false, stdout.String(), nil
}
