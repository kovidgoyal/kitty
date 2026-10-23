// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"fmt"
	shm "github.com/kovidgoyal/go-shm/v2"
	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/themes"
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

func TestSSHChangeColors(t *testing.T) {
	tdir := t.TempDir()
	write_conf := func(name, text string) string {
		p := filepath.Join(tdir, name)
		if err := os.WriteFile(p, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
		return p
	}
	a := write_conf("a.conf", "background #010101\nforeground #020202\ncolor1 #030303\n")
	b := write_conf("b.conf", "background #fefefe\ncolor1 #fdfdfd\n")
	settings := func(p string) map[string]string {
		s, err := load_color_schemes(p)
		if err != nil {
			t.Fatal(err)
		}
		return s[p]
	}
	change := func(c Config) string {
		ans, err := change_colors(&c)
		if err != nil {
			t.Fatal(err)
		}
		return ans
	}
	// existing configs with only color_scheme use escape codes
	if ans := change(Config{}); ans != "" {
		t.Fatalf("Colors changed with no color scheme: %#v", ans)
	}
	if ans := change(Config{Color_scheme: a}); ans != "\x1b[#P"+themes.ColorSettingsAsEscapeCodes(settings(a)) {
		t.Fatalf("Incorrect escape codes for color_scheme: %#v", ans)
	}
	if _, err := change_colors(&Config{Color_scheme_dark: filepath.Join(tdir, "missing.conf")}); err == nil {
		t.Fatal("No error for missing color scheme file")
	}

	variants := func(c Config) map[string]any {
		ans := change(c)
		prefix := "\x1b[#P\x1bP@kitty-color-scheme|"
		if !strings.HasPrefix(ans, prefix) || !strings.HasSuffix(ans, "\x1b\\") {
			t.Fatalf("Incorrect escape code for color scheme variants: %#v", ans)
		}
		data, err := base64.StdEncoding.DecodeString(ans[len(prefix) : len(ans)-2])
		if err != nil {
			t.Fatal(err)
		}
		var payload map[string]any
		if err = json.Unmarshal(data, &payload); err != nil {
			t.Fatal(err)
		}
		return payload
	}
	spec := func(p string) any {
		data, err := json.Marshal(themes.ColorSettingsAsSpec(settings(p)))
		if err != nil {
			t.Fatal(err)
		}
		var ans any
		if err = json.Unmarshal(data, &ans); err != nil {
			t.Fatal(err)
		}
		return ans
	}
	// color_scheme is used for modes without a specific color scheme
	if diff := cmp.Diff(map[string]any{"dark": spec(b), "light": spec(a), "no_preference": spec(a)}, variants(Config{Color_scheme: a, Color_scheme_dark: b})); diff != "" {
		t.Fatalf("Incorrect color scheme variants:\n%s", diff)
	}
	// modes without any color scheme use the colors from kitty
	if diff := cmp.Diff(map[string]any{"light": spec(b)}, variants(Config{Color_scheme_light: b})); diff != "" {
		t.Fatalf("Incorrect color scheme variants:\n%s", diff)
	}
}
