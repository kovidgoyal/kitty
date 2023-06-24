// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"fmt"
	"kitty/tools/utils"
	"os"
	"path/filepath"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestSSHConfigParsing(t *testing.T) {
	tdir := t.TempDir()
	hostname := "unmatched"
	username := ""
	conf := ""
	for_python := false
	cf := filepath.Join(tdir, "ssh.conf")
	rt := func(expected_env ...string) {
		os.WriteFile(cf, []byte(conf), 0o600)
		c, bad_lines, err := load_config(hostname, username, nil, cf)
		if err != nil {
			t.Fatal(err)
		}
		if len(bad_lines) != 0 {
			t.Fatalf("Bad config line: %s with error: %s", bad_lines[0].Line, bad_lines[0].Err)
		}
		actual := final_env_instructions(for_python, func(key string) (string, bool) {
			if key == "LOCAL_ENV" {
				return "LOCAL_VAL", true
			}
			return "", false
		}, c.Env...)
		if expected_env == nil {
			expected_env = []string{}
		}
		diff := cmp.Diff(expected_env, utils.Splitlines(actual))
		if diff != "" {
			t.Fatalf("Unexpected env for\nhostname: %#v\nusername: %#v\nconf: %s\n%s", hostname, username, conf, diff)
		}
	}
	rt()
	conf = "env a=b"
	rt(`export 'a'="b"`)
	conf = "env a=b\nhostname 2\nenv a=c\nenv b=b"
	rt(`export 'a'="b"`)
	hostname = "2"
	rt(`export 'a'="c"`, `export 'b'="b"`)
	conf = "env a="
	rt(`export 'a'=""`)
	conf = "env a"
	rt(`unset 'a'`)
	conf = "env a=b\nhostname test@2\nenv a=c\nenv b=b"
	hostname = "unmatched"
	rt(`export 'a'="b"`)
	hostname = "2"
	rt(`export 'a'="b"`)
	username = "test"
	rt(`export 'a'="c"`, `export 'b'="b"`)
	conf = "env a=b\nhostname 1 2\nenv a=c\nenv b=b"
	username = ""
	hostname = "unmatched"
	rt(`export 'a'="b"`)
	hostname = "1"
	rt(`export 'a'="c"`, `export 'b'="b"`)
	hostname = "2"
	rt(`export 'a'="c"`, `export 'b'="b"`)
	for_python = true
	rt(`export ["a","c",false]`, `export ["b","b",false]`)
	conf = "env a="
	rt(`export ["a"]`)
	conf = "env a"
	rt(`unset ["a"]`)
	conf = "env LOCAL_ENV=_kitty_copy_env_var_"
	rt(`export ["LOCAL_ENV","LOCAL_VAL",false]`)
	conf = "env a=b\nhostname 2\ncolor_scheme xyz"
	hostname = "2"
	rt()

	ci, err := ParseCopyInstruction("--exclude moose --dest=target " + cf)
	if err != nil {
		t.Fatal(err)
	}
	diff := cmp.Diff("home/target", ci[0].arcname)
	if diff != "" {
		t.Fatalf("Incorrect arcname:\n%s", diff)
	}
	diff = cmp.Diff(cf, ci[0].local_path)
	if diff != "" {
		t.Fatalf("Incorrect local_path:\n%s", diff)
	}
	diff = cmp.Diff([]string{"moose"}, ci[0].exclude_patterns)
	if diff != "" {
		t.Fatalf("Incorrect excludes:\n%s", diff)
	}
	ci, err = ParseCopyInstruction("--glob " + filepath.Join(filepath.Dir(cf), "*.conf"))
	if err != nil {
		t.Fatal(err)
	}
	diff = cmp.Diff(cf, ci[0].local_path)
	if diff != "" {
		t.Fatalf("Incorrect local_path:\n%s", diff)
	}
	if len(ci) != 1 {
		t.Fatal(ci)
	}

}
