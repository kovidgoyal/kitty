// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/kovidgoyal/datty/tools/utils/shlex"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestGetSSHOptions(t *testing.T) {
	m := SSHOptions()
	if m["w"] != "local_tun[:remote_tun]" {

		cmd := exec.Command(SSHExe())
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		cmd.Run()
		t.Fatalf("Unexpected set of SSH options: %#v", m)
	}
}

func TestParseSSHArgs(t *testing.T) {
	split := func(x string) []string {
		ans, err := shlex.Split(x)
		if err != nil {
			t.Fatal(err)
		}
		if len(ans) == 0 {
			ans = []string{}
		}
		return ans
	}

	p := func(args, expected_ssh_args, expected_server_args, expected_extra_args string, expected_passthrough bool) {
		ssh_args, server_args, passthrough, extra_args, err := ParseSSHArgs(split(args), "--daddy")
		if err != nil {
			t.Fatal(err)
		}
		check := func(a, b any) {
			diff := cmp.Diff(a, b)
			if diff != "" {
				t.Fatalf("Unexpected value for args: %#v\n%s", args, diff)
			}
		}
		check(split(expected_ssh_args), ssh_args)
		check(split(expected_server_args), server_args)
		check(split(expected_extra_args), extra_args)
		check(expected_passthrough, passthrough)
	}
	p(`localhost`, ``, `localhost`, ``, false)
	p(`-- localhost`, ``, `localhost`, ``, false)
	p(`-46p23 localhost sh -c "a b"`, `-4 -6 -p 23`, `localhost sh -c "a b"`, ``, false)
	p(`-46p23 -S/moose -W x:6 -- localhost sh -c "a b"`, `-4 -6 -p 23 -S /moose -W x:6`, `localhost sh -c "a b"`, ``, false)
	p(`--daddy=abc -np23 --daddy xyz host`, `-n -p 23`, `host`, `--daddy abc --daddy xyz`, true)
	p(`--daddy cwd=/tmp -p 2222 -i key host`, `-p 2222 -i key`, `host`, `--daddy cwd=/tmp`, false)
}

func TestRelevantDattyOpts(t *testing.T) {
	tdir := t.TempDir()
	path := filepath.Join(tdir, "datty.conf")
	os.WriteFile(path, []byte("term XXX\nshell_integration changed\nterm abcd"), 0o600)
	rko := read_relevant_datty_opts(path)
	if rko.Term != "abcd" {
		t.Fatalf("Unexpected TERM: %s", RelevantDattyOpts().Term)
	}
	if rko.Shell_integration != "changed" {
		t.Fatalf("Unexpected shell_integration: %s", RelevantDattyOpts().Shell_integration)
	}
}
