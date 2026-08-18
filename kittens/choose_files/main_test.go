// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_files

import (
	"path/filepath"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

func TestShellOutput(t *testing.T) {
	paths := []string{"simple", "a path", "a;command", "*.txt", "~root", "a>output", `a\b`, "it's"}
	actual, err := shlex.Split(shell_output(paths))
	if err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff(paths, actual); diff != "" {
		t.Fatalf("Shell output did not round-trip paths:\n%s", diff)
	}
	if q := shell_output([]string{"simple", "a/b"}); q != "simple a/b" {
		t.Fatalf("Shell-safe paths were unnecessarily quoted: %q", q)
	}

	original_cwd := default_cwd
	default_cwd = t.TempDir()
	t.Cleanup(func() { default_cwd = original_cwd })
	relative, err := shlex.Split(for_shell_relative(filepath.Join(default_cwd, "a;command")))
	if err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]string{"a;command"}, relative); diff != "" {
		t.Fatalf("Shell-relative output did not round-trip the path:\n%s", diff)
	}
}
