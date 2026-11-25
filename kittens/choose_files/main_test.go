// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_files

import (
	"path/filepath"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
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

func TestChooseFilesLoopSetup(t *testing.T) {
	original_cwd := default_cwd
	t.Cleanup(func() { default_cwd = original_cwd })

	lp, err := loop.New()
	if err != nil {
		t.Fatal(err)
	}
	opts := &Options{}
	conf := &Config{}
	h, err := setup_loop(lp, opts, conf, []string{t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	if h == nil {
		t.Fatal("expected handler to be non-nil")
	}
	if lp.KittenRequiringKeyboardProtocol() != kittenName {
		t.Fatalf("expected loop to require keyboard protocol for %q, got %q", kittenName, lp.KittenRequiringKeyboardProtocol())
	}
	if lp.OnInitialize == nil {
		t.Fatal("expected OnInitialize to be registered")
	}
	if lp.OnFinalize == nil {
		t.Fatal("expected OnFinalize to be registered")
	}
	if lp.OnResize == nil {
		t.Fatal("expected OnResize to be registered")
	}
	if lp.OnColorSchemeChange == nil {
		t.Fatal("expected OnColorSchemeChange to be registered")
	}
	if lp.OnKeyEvent == nil {
		t.Fatal("expected OnKeyEvent to be registered")
	}
	if lp.OnText == nil {
		t.Fatal("expected OnText to be registered")
	}
	if lp.OnMouseEvent == nil {
		t.Fatal("expected OnMouseEvent to be registered")
	}
	if lp.OnEscapeCode == nil {
		t.Fatal("expected OnEscapeCode to be registered")
	}
	if lp.OnWakeup == nil {
		t.Fatal("expected OnWakeup to be registered")
	}
}
