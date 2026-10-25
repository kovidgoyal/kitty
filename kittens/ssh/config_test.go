// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"archive/tar"
	"fmt"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/paths"
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

func TestSSHCopyArcnames(t *testing.T) {
	for _, tc := range []struct {
		name, loc, dest, home, expected string
	}{
		{"home", "/home/alice", "", "/home/alice", "home/."},
		{"inside home", "/home/alice/.config/app", "", "/home/alice", "home/.config/app"},
		{"sibling directory", "/home/alice-backup/config", "", "/home/alice", "root/home/alice-backup/config"},
		{"sibling user", "/home/alice2/config", "", "/home/alice", "root/home/alice2/config"},
		{"outside home", "/etc/config", "", "/home/alice", "root/etc/config"},
		{"cleaned path", "/home/alice/../alice-backup/config", "", "/home/alice", "root/home/alice-backup/config"},
		{"trailing slash", "/home/alice/.config/app", "", "/home/alice/", "home/.config/app"},
		{"root home", "/etc/config", "", "/", "home/etc/config"},
		{"relative destination", "/home/alice-backup/config", "config", "/home/alice", "home/config"},
		{"absolute destination", "/home/alice/config", "/etc/config", "/home/alice", "root/etc/config"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if actual := get_arcname(tc.loc, tc.dest, tc.home); actual != tc.expected {
				t.Fatalf("Incorrect arcname: %q != %q", actual, tc.expected)
			}
		})
	}
}

func TestSSHCopySymlinkedHome(t *testing.T) {
	tdir := t.TempDir()
	real_home := filepath.Join(tdir, "usr", "home", "alice")
	if err := os.MkdirAll(real_home, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(tdir, "usr", "home"), filepath.Join(tdir, "home")); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(real_home, "config"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	home := filepath.Join(tdir, "home", "alice")
	orig_paths_ctx := paths_ctx
	defer func() { paths_ctx = orig_paths_ctx }()
	paths_ctx = &paths.Ctx{}
	paths_ctx.SetHome(home)
	for _, strategy := range []string{"preserve", "keep-path", "resolve"} {
		t.Run(strategy, func(t *testing.T) {
			ci, err := ParseCopyInstruction("--symlink-strategy=" + strategy + " " + filepath.Join(home, "config"))
			if err != nil {
				t.Fatal(err)
			}
			if ci[0].arcname != "home/config" {
				t.Fatalf("Incorrect arcname: %q != %q", ci[0].arcname, "home/config")
			}
		})
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
		{"other", 0o711},
	}
	for _, d := range dirs {
		name := filepath.Join(root, d.name)
		if err := os.MkdirAll(name, 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.Chmod(name, d.mode); err != nil {
			t.Fatal(err)
		}
	}
	// symlinks to directories must be copied as symlinks
	if err := os.Symlink("private", filepath.Join(root, "link")); err != nil {
		t.Fatal(err)
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
		if h.Typeflag != tar.TypeDir {
			t.Errorf("%s: not a directory", name)
		}
		if h.Mode != int64(d.mode) {
			t.Errorf("%s: permissions %04o != %04o", name, h.Mode, d.mode)
		}
		if expected := time.Unix(1600000000+int64(i)*60, 0); !h.ModTime.Equal(expected) {
			t.Errorf("%s: modification time %s != %s", name, h.ModTime, expected)
		}
	}
	if h := headers["home/tree/link"]; h.Typeflag != tar.TypeSymlink || h.Linkname != "private" {
		t.Errorf("Symlink to directory not copied as symlink: %#v", h)
	}
}
