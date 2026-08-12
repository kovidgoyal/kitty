// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package remote_file

import (
	"fmt"
	"os"
	"slices"
	"testing"
)

func TestParseConnData(t *testing.T) {
	c, err := parse_conn_data(`["ssh", "myhost", 2222, "/id/file"]`)
	if err != nil {
		t.Fatal(err)
	}
	if c.Binary != "ssh" || c.Hostname != "myhost" || c.Port != 2222 || c.IdentityFile != "/id/file" || c.IsSSHKitten {
		t.Fatalf("bad conn data: %+v", c)
	}

	c, err = parse_conn_data(`["ssh", "shorthost"]`)
	if err != nil || c.Port != 0 || c.IdentityFile != "" {
		t.Fatalf("optional fields: %+v err=%v", c, err)
	}

	raw := fmt.Sprintf(`["%s", "kitten", "ssh", "-t", "somehost", "cmd"]`, is_ssh_kitten_sentinel)
	c, err = parse_conn_data(raw)
	if err != nil {
		t.Fatal(err)
	}
	if !c.IsSSHKitten || c.Hostname != "cmd" || !slices.Equal(c.SSHKittenCmdline, []string{"kitten", "ssh"}) {
		t.Fatalf("ssh kitten form: %+v", c)
	}
}

func TestCmdPrefixes(t *testing.T) {
	c := &SSHConnectionData{Binary: "ssh", Hostname: "h", Port: 2222, IdentityFile: "/id"}
	p := c.cmd_prefix()
	want := []string{
		"ssh", "-o", fmt.Sprintf("ControlPath=~/.ssh/kitty-rf-%d-%%C", os.Getpid()),
		"-o", "TCPKeepAlive=yes", "-o", "ControlPersist=yes", "-p", "2222", "-i", "/id",
	}
	if !slices.Equal(p, want) {
		t.Fatalf("cmd_prefix:\n got %q\nwant %q", p, want)
	}
	b := c.batch_cmd_prefix()
	if !slices.Equal(b, append(slices.Clone(want), "-o", "BatchMode=yes")) {
		t.Fatalf("batch_cmd_prefix: %q", b)
	}
	sk := &SSHConnectionData{IsSSHKitten: true, SSHKittenCmdline: []string{"kitten", "ssh"}}
	if !slices.Equal(sk.batch_cmd_prefix(), []string{"kitten", "ssh"}) {
		t.Fatalf("ssh-kitten batch prefix must not add BatchMode: %q", sk.batch_cmd_prefix())
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
