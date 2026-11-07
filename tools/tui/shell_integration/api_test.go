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

func TestBashSysStartupFilesScan(t *testing.T) {
	type res struct {
		profile, bashrc string
		found           bool
	}
	for data, expected := range map[string]res{
		"\x00/etc/bash.bash_logout\x00/etc/bash.bashrc\x00~/.bashrc\x00/etc/profile\x00~/.bash_profile\x00": {"/etc/profile", "/etc/bash.bashrc", true},
		"xx\x01/usr/share/defaults/etc/profile\x00/usr/share/defaults/etc/bashrc\x00":                       {"/usr/share/defaults/etc/profile", "/usr/share/defaults/etc/bashrc", true},
		"\x00/etc/profile\x00/etc/skel/.bashrc\x00":                                                         {"/etc/profile", "", true},
		"\x00/etc/bash/bashrc\x00use /etc/profile\x00/etc/profile.d\x00":                                    {"", "", false},
		"": {"", "", false},
	} {
		var actual res
		actual.profile, actual.bashrc, actual.found = bash_sys_startup_files_from_binary_data([]byte(data))
		if actual != expected {
			t.Fatalf("Scanning %#v gave %#v instead of %#v", data, actual, expected)
		}
	}
}
