// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package remote_file

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestParseConnData(t *testing.T) {
	c, err := parse_conn_data(`["ssh", "myhost", 2222, "/id/file"]`)
	if err != nil {
		t.Fatal(err)
	}
	if c.Binary != "ssh" || c.Hostname != "myhost" || c.Port != 2222 || c.IdentityFile != "/id/file" || c.IsSSHDaddy {
		t.Fatalf("bad conn data: %+v", c)
	}

	c, err = parse_conn_data(`["ssh", "shorthost"]`)
	if err != nil || c.Port != 0 || c.IdentityFile != "" {
		t.Fatalf("optional fields: %+v err=%v", c, err)
	}

	raw := fmt.Sprintf(`["%s", "daddy", "ssh", "-t", "somehost", "cmd"]`, is_ssh_daddy_sentinel)
	c, err = parse_conn_data(raw)
	if err != nil {
		t.Fatal(err)
	}
	if !c.IsSSHDaddy || c.Hostname != "cmd" || !slices.Equal(c.SSHDaddyCmdline, []string{"daddy", "ssh"}) {
		t.Fatalf("ssh daddy form: %+v", c)
	}
}

func TestCmdPrefixes(t *testing.T) {
	c := &SSHConnectionData{Binary: "ssh", Hostname: "h", Port: 2222, IdentityFile: "/id"}
	p := c.cmd_prefix()
	want := []string{
		"ssh", "-o", fmt.Sprintf("ControlPath=~/.ssh/datty-rf-%d-%%C", os.Getpid()),
		"-o", "TCPKeepAlive=yes", "-o", "ControlPersist=yes", "-p", "2222", "-i", "/id",
	}
	if !slices.Equal(p, want) {
		t.Fatalf("cmd_prefix:\n got %q\nwant %q", p, want)
	}
	b := c.batch_cmd_prefix()
	if !slices.Equal(b, append(slices.Clone(want), "-o", "BatchMode=yes")) {
		t.Fatalf("batch_cmd_prefix: %q", b)
	}
	sk := &SSHConnectionData{IsSSHDaddy: true, SSHDaddyCmdline: []string{"daddy", "ssh"}}
	if !slices.Equal(sk.batch_cmd_prefix(), []string{"daddy", "ssh"}) {
		t.Fatalf("ssh-daddy batch prefix must not add BatchMode: %q", sk.batch_cmd_prefix())
	}
}

func TestHostnameMatches(t *testing.T) {
	for _, tc := range []struct {
		a, b string
		want bool
	}{
		{"foo", "foo", true},
		{"foo.example.com", "foo.local", true},
		{"foo", "bar", false},
	} {
		if hostname_matches(tc.a, tc.b) != tc.want {
			t.Fatalf("hostname_matches(%q, %q) != %v", tc.a, tc.b, tc.want)
		}
	}
}

func TestAutoRenameDest(t *testing.T) {
	taken := map[string]bool{"/x/a.txt": true, "/x/a-1.txt": true}
	got := auto_rename_dest("/x/a.txt", func(p string) bool { return taken[p] })
	if got != "/x/a-2.txt" {
		t.Fatalf("auto_rename_dest: %q", got)
	}
}

func TestAutoRenameDotfile(t *testing.T) {
	taken := map[string]bool{"/x/.bashrc": true}
	got := auto_rename_dest("/x/.bashrc", func(p string) bool { return taken[p] })
	if got != "/x/.bashrc-1" {
		t.Fatalf("auto_rename_dest dotfile: got %q, want /x/.bashrc-1", got)
	}
}

func TestParseConnDataSSHDaddyEdge(t *testing.T) {
	// ssh-daddy with exactly 1 cmdline item after sentinel should result in empty SSHDaddyCmdline
	raw := fmt.Sprintf(`["%s", "onlyitem"]`, is_ssh_daddy_sentinel)
	c, err := parse_conn_data(raw)
	if err != nil {
		t.Fatal(err)
	}
	if !c.IsSSHDaddy || c.Hostname != "onlyitem" || len(c.SSHDaddyCmdline) != 0 {
		t.Fatalf("ssh daddy edge case (single item): %+v, SSHDaddyCmdline=%v", c, c.SSHDaddyCmdline)
	}
}

func TestPythonSplitExt(t *testing.T) {
	// Table-driven test for pythonSplitExt matching os.path.splitext semantics.
	// Expected values from Python 3: python3 -c "import os; print(os.path.splitext(f))" for each.
	// Reference run: 2026-08-12
	for _, tc := range []struct {
		input    string
		wantBase string
		wantExt  string
	}{
		// Dotfiles with no extension in remainder (leading dots only)
		{".bashrc", ".bashrc", ""},
		{"..bashrc", "..bashrc", ""},
		{"...", "...", ""},
		{"..", "..", ""},
		{"....txt", "....txt", ""}, // 4 leading dots, then "txt" with no dot

		// Dotfiles with extension in remainder
		{".bashrc.bak", ".bashrc", ".bak"},

		// Normal files
		{"a.b.c", "a.b", ".c"},
		{"a.txt", "a", ".txt"},
		{"plain", "plain", ""},
	} {
		base, ext := pythonSplitExt(tc.input)
		if base != tc.wantBase || ext != tc.wantExt {
			t.Fatalf("pythonSplitExt(%q):\n  got (%q, %q)\n  want (%q, %q)",
				tc.input, base, ext, tc.wantBase, tc.wantExt)
		}
	}
}

func TestRemoteEditFinalUpload(t *testing.T) {
	const ssh_script = `#!/bin/sh
for arg in "$@"; do
    case "$arg" in
        -fN) exit 0 ;;
        check)
            if [ "$DATTY_TEST_SSH_MODE" = master-died ] && [ -f "$DATTY_TEST_EDITED_PATH" ]; then exit 255; fi
            exit 0 ;;
        exit) touch "$DATTY_TEST_SSH_CLOSED"; exit 0 ;;
        hostname) printf 'test-host\n'; exit 0 ;;
        '>')
            if [ "$DATTY_TEST_SSH_MODE" != success ]; then cat >/dev/null; exit 255; fi
            cat > "$DATTY_TEST_REMOTE_FILE"; exit $? ;;
    esac
done
cat "$DATTY_TEST_REMOTE_FILE"
`
	const editor_script = `#!/bin/sh
printf 'edited content\n' > "$1"
printf '%s' "$1" > "$DATTY_TEST_EDITED_PATH"
`
	for _, tc := range []struct {
		name, mode                 string
		ssh_daddy, editor_missing bool
		want_error, want_copy      bool
	}{
		{name: "uploaded", mode: "success"},
		{name: "upload_failed", mode: "upload-failed", want_error: true, want_copy: true},
		{name: "master_died", mode: "master-died", want_error: true, want_copy: true},
		{name: "editor_start_failed", mode: "success", editor_missing: true, want_error: true},
		{name: "ssh_daddy_uploaded", mode: "success", ssh_daddy: true},
		{name: "ssh_daddy_upload_failed", mode: "upload-failed", ssh_daddy: true, want_error: true, want_copy: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			directory := t.TempDir()
			remote := filepath.Join(directory, "remote.txt")
			ssh := filepath.Join(directory, "ssh")
			editor := filepath.Join(directory, "editor")
			closed := filepath.Join(directory, "closed")
			t.Setenv("DATTY_TEST_REMOTE_FILE", remote)
			t.Setenv("DATTY_TEST_EDITED_PATH", filepath.Join(directory, "edited-path"))
			t.Setenv("DATTY_TEST_SSH_CLOSED", closed)
			t.Setenv("DATTY_TEST_SSH_MODE", tc.mode)
			for path, data := range map[string]string{remote: "original content\n", ssh: ssh_script, editor: editor_script} {
				if err := os.WriteFile(path, []byte(data), 0700); err != nil {
					t.Fatal(err)
				}
			}
			conn := &SSHConnectionData{Binary: ssh, Hostname: "test-host", IsSSHDaddy: tc.ssh_daddy, SSHDaddyCmdline: []string{ssh}}
			master := new_control_master(conn, "/remote/note with spaces.txt", "")
			if err := master.Start(); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() {
				master.Close()
				_ = os.RemoveAll(master.tdir)
			})
			if err := master.Download(); err != nil {
				t.Fatal(err)
			}
			if tc.editor_missing {
				editor = filepath.Join(directory, "missing-editor")
			}
			err := func() error {
				defer master.Close()
				return edit_and_upload(master, []string{editor})
			}()
			if (err != nil) != tc.want_error {
				t.Fatalf("edit_loop error: %v, want error: %v", err, tc.want_error)
			}
			data, read_err := os.ReadFile(master.Dest)
			if tc.want_copy {
				if read_err != nil || string(data) != "edited content\n" {
					t.Errorf("edited copy was not retained after cleanup: %q, %v", data, read_err)
				}
				if !strings.Contains(err.Error(), master.Dest) {
					t.Errorf("upload error does not identify the recovery path: %v", err)
				}
			} else if !os.IsNotExist(read_err) {
				t.Errorf("temporary copy was not cleaned up: %v", read_err)
			}
			data, read_err = os.ReadFile(remote)
			want := "original content\n"
			if !tc.want_error {
				want = "edited content\n"
			}
			if read_err != nil || string(data) != want {
				t.Errorf("remote contents: %q, %v, want %q", data, read_err, want)
			}
			_, close_err := os.Stat(closed)
			if !tc.ssh_daddy && close_err != nil {
				t.Error("SSH control connection was not closed:", close_err)
			} else if tc.ssh_daddy && !os.IsNotExist(close_err) {
				t.Error("borrowed ssh daddy connection was closed")
			}
		})
	}
}
