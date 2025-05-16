// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/utils/shm"
	"io/fs"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func TestCloneEnv(t *testing.T) {
	env := map[string]string{"a": "1", "b": "2"}
	data, err := json.Marshal(env)
	if err != nil {
		t.Fatal(err)
	}
	mmap, err := shm.CreateTemp("", 128)
	if err != nil {
		t.Fatal(err)
	}
	defer mmap.Unlink()
	copy(mmap.Slice()[4:], data)
	binary.BigEndian.PutUint32(mmap.Slice(), uint32(len(data)))
	mmap.Close()
	x, err := add_cloned_env(mmap.Name())
	if err != nil {
		t.Fatal(err)
	}
	diff := cmp.Diff(env, x)
	if diff != "" {
		t.Fatalf("Failed to deserialize env\n%s", diff)
	}
}

func basic_connection_data(overrides ...string) *connection_data {
	ans := &connection_data{
		script_type: "sh", request_id: "123-123", remote_args: []string{},
		username: "testuser", hostname_for_match: "host.test",
		dont_create_shm: true,
	}
	opts, bad_lines, err := load_config(ans.hostname_for_match, ans.username, overrides)
	if err != nil {
		panic(err)
	}
	if len(bad_lines) != 0 {
		panic(fmt.Sprintf("Bad config lines: %s with error: %s", bad_lines[0].Line, bad_lines[0].Err))
	}
	ans.host_opts = opts
	return ans
}

func TestSSHBootstrapScriptLimit(t *testing.T) {
	cd := basic_connection_data()
	err := get_remote_command(cd)
	if err != nil {
		t.Fatal(err)
	}
	total := 0
	for _, x := range cd.rcmd {
		total += len(x)
	}
	if total > 9000 {
		t.Fatalf("Bootstrap script too large: %d bytes", total)
	}
}

func TestSSHTarfile(t *testing.T) {
	tdir := t.TempDir()
	cd := basic_connection_data()
	data, err := make_tarfile(cd, func(key string) (val string, found bool) { return })
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("tar", "xpzf", "-", "-C", tdir)
	cmd.Stderr = os.Stderr
	inp, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	err = cmd.Start()
	if err != nil {
		t.Fatal(err)
	}
	_, err = inp.Write(data)
	if err != nil {
		t.Fatal(err)
	}
	inp.Close()
	err = cmd.Wait()
	if err != nil {
		t.Fatal(err)
	}

	seen := map[string]bool{}
	err = filepath.WalkDir(tdir, func(name string, d fs.DirEntry, werr error) error {
		if werr != nil {
			return werr
		}
		rname, werr := filepath.Rel(tdir, name)
		if werr != nil {
			return werr
		}
		rname = strings.ReplaceAll(rname, "\\", "/")
		if rname == "." {
			return nil
		}
		fi, werr := d.Info()
		if werr != nil {
			return werr
		}
		if fi.Mode().Perm()&0o600 == 0 {
			return fmt.Errorf("%s is not rw for its owner. Actual permissions: %s", rname, fi.Mode().String())
		}
		seen[rname] = true
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if !seen["data.sh"] {
		t.Fatalf("data.sh missing")
	}
	for _, x := range []string{".terminfo/kitty.terminfo", ".terminfo/x/" + kitty.DefaultTermName} {
		if !seen["home/"+x] {
			t.Fatalf("%s missing", x)
		}
	}
	for _, x := range []string{"shell-integration/bash/kitty.bash", "shell-integration/fish/vendor_completions.d/kitty.fish"} {
		if !seen[path.Join("home", cd.host_opts.Remote_dir, x)] {
			t.Fatalf("%s missing", x)
		}
	}
	for _, x := range []string{"kitty", "kitten"} {
		p := filepath.Join(tdir, "home", cd.host_opts.Remote_dir, "kitty", "bin", x)
		if err = unix.Access(p, unix.X_OK); err != nil {
			t.Fatalf("Cannot execute %s with error: %s", x, err)
		}
	}
	if seen[path.Join("home", cd.host_opts.Remote_dir, "shell-integration", "ssh", "kitten")] {
		t.Fatalf("Contents of shell-integration/ssh not excluded")
	}
}
