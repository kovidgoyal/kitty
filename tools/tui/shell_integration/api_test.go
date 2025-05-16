// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package shell_integration

import (
	"bytes"
	"fmt"
	"github.com/kovidgoyal/kitty"
	"os"
	"path/filepath"
	"testing"
)

var _ = fmt.Print

func TestExtractShellIntegration(t *testing.T) {
	tdir := t.TempDir()
	if err := extract_shell_integration_for("zsh", tdir); err != nil {
		t.Fatal(err)
	}
	kzsh := filepath.Join(tdir, "shell-integration", "zsh", "kitty.zsh")
	if _, err := os.Stat(kzsh); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(tdir, "shell-integration", "zsh", "completions", "_kitty")); err != nil {
		t.Fatal(err)
	}
	orig, err := os.ReadFile(kzsh)
	if err != nil {
		t.Fatal(err)
	}
	_ = os.WriteFile(kzsh, []byte("changed"), 0o644)
	if err := extract_shell_integration_for("zsh", tdir); err != nil {
		t.Fatal(err)
	}
	changed, err := os.ReadFile(kzsh)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(changed, orig) {
		t.Fatalf("Failed to update shell integration file")
	}

	if err = extract_terminfo(tdir); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(tdir, "terminfo", "78", kitty.DefaultTermName)); err != nil {
		t.Fatal(err)
	}
	TerminfoData()
}
