// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"archive/tar"
	"fmt"
	"github.com/kovidgoyal/kitty/tools/utils"
	"os"
	"os/user"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

type Pair struct {
	Input, Uname, Host string
}

func TestSSHConfigParsing(t *testing.T) {
	tdir := t.TempDir()
	hostname := "unmatched"
	username := ""
	conf := ""
	overrides := []string{}
	for_python := false
	cf := filepath.Join(tdir, "ssh.conf")
	rt := func(expected_env ...string) {
		if err := os.WriteFile(cf, []byte(conf), 0o600); err != nil {
			t.Fatal(err)
		}
		c, bad_lines, err := load_config(hostname, username, overrides, cf)
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
	conf = "env a=b"
	overrides = []string{"env=c=d"}
	rt(`export 'a'="b"`, `export 'c'="d"`)
	overrides = nil

	conf = "env a=\\"
	rt(`export 'a'="\\"`)
	conf = `env
		\ a=
		\\`
	conf = "env\n \t \\ a=\n\\\\"
	rt(`export 'a'="\\"`)
	conf = `
		e
		\n
		\v
		\ a
		\=
		\\
		\`
	rt(`export 'a'="\\"`)

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

	ci, err := ParseCopyInstruction("--exclude moose --exclude second --dest=target " + cf)
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
	diff = cmp.Diff([]string{"moose", "second"}, ci[0].exclude_patterns)
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

	u, _ := user.Current()
	un := u.Username
	for _, x := range []Pair{
		{"localhost:12", un, "localhost:12"},
		{"@localhost", un, "@localhost"},
		{"ssh://@localhost:33", un, "localhost"},
		{"me@localhost", "me", "localhost"},
		{"ssh://me@localhost:12/something?else=1", "me", "localhost"},
	} {
		ue, uh := get_destination(x.Input)
		q := Pair{x.Input, ue, uh}
		if diff := cmp.Diff(x, q); diff != "" {
			t.Fatalf("Failed: %s", diff)
		}
	}

}

func TestSSHCopyDirectoryMetadata(t *testing.T) {
	root := filepath.Join(t.TempDir(), "tree")
	dirs := []struct {
		name string
		mode os.FileMode
	}{
		{"", 0o755},
		{"private", 0o700},
		{"private/nested", 0o750},
	}
	for _, d := range dirs {
		name := filepath.Join(root, d.name)
		if err := os.MkdirAll(name, d.mode); err != nil {
			t.Fatal(err)
		}
		if err := os.Chmod(name, d.mode); err != nil {
			t.Fatal(err)
		}
	}
	for i, d := range dirs {
		stamp := time.Unix(1600000000+int64(i)*60, 0)
		if err := os.Chtimes(filepath.Join(root, d.name), stamp, stamp); err != nil {
			t.Fatal(err)
		}
	}
	headers := make(map[string]tar.Header)
	ci := CopyInstruction{local_path: root, arcname: "home/tree"}
	if err := ci.get_file_data(func(h *tar.Header, data []byte) error {
		headers[strings.TrimSuffix(h.Name, "/")] = *h
		return nil
	}, make(map[file_unique_id]string)); err != nil {
		t.Fatal(err)
	}
	for i, d := range dirs {
		name := filepath.ToSlash(filepath.Join("home/tree", d.name))
		h, found := headers[name]
		if !found {
			t.Fatalf("Missing directory: %s", name)
		}
		if h.Mode != int64(d.mode) {
			t.Errorf("%s: permissions %04o != %04o", name, h.Mode, d.mode)
		}
		if expected := time.Unix(1600000000+int64(i)*60, 0); !h.ModTime.Equal(expected) {
			t.Errorf("%s: modification time %s != %s", name, h.ModTime, expected)
		}
	}
}
