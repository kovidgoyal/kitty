// License: GPLv3 Copyright: 2026, kitty contributors

package desktop_ui

import (
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

func TestInvalidAccentColor(t *testing.T) {
	if _, err := to_color("cyan"); err != nil {
		t.Fatalf("Valid accent color rejected: %s", err)
	}
	if v, err := to_color("not-a-color"); err == nil {
		t.Fatalf("Invalid accent color accepted as: %#v", v)
	}
	c := NewConfig()
	if err := c.Parse("accent_color", "not-a-color"); err == nil {
		t.Fatalf("Invalid accent_color accepted in config as: %#v", c.Accent_color)
	}
	if c.Accent_color != NewConfig().Accent_color {
		t.Fatalf("Invalid accent_color in config changed the default to: %#v", c.Accent_color)
	}
}

func TestPortalExecPath(t *testing.T) {
	if os.Getenv("KITTY_TEST_PORTAL_EXEC") == "1" {
		if err := enable_portal(); err != nil {
			t.Fatal(err)
		}
		return
	}

	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(exe)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct{ name, directory string }{
		{"plain", "kitty"}, {"space", "kitty app"},
		{"single_quote", "kitty'app"}, {"double_quote", "kitty\"app"},
		{"backslash", `kitty\app`}, {"dollar", "kitty$app"},
		{"tab", "kitty\tapp"}, {"newline", "kitty\napp"}, {"carriage_return", "kitty\rapp"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			copied_exe := filepath.Join(dir, tc.directory, "kitten")
			data_dir := filepath.Join(dir, "data")
			for _, p := range []string{filepath.Dir(copied_exe), data_dir} {
				if err := os.MkdirAll(p, 0o700); err != nil {
					t.Fatal(err)
				}
			}
			if err := os.WriteFile(copied_exe, raw, 0o700); err != nil {
				t.Fatal(err)
			}
			cmd := exec.Command(copied_exe, "-test.run=^TestPortalExecPath$")
			cmd.Env = append(os.Environ(), "KITTY_TEST_PORTAL_EXEC=1",
				"XDG_DATA_HOME="+data_dir, "XDG_DATA_DIRS="+data_dir,
				"XDG_CONFIG_HOME="+filepath.Join(dir, "config"), "XDG_CURRENT_DESKTOP=probe")
			if output, err := cmd.CombinedOutput(); err != nil {
				t.Fatalf("enable-portal failed: %s\n%s", err, output)
			}
			service, err := os.ReadFile(filepath.Join(data_dir, "dbus-1", "services", PORTAL_BUS_NAME+".service"))
			if err != nil {
				t.Fatal(err)
			}
			var command_line string
			for _, line := range strings.Split(string(service), "\n") {
				if value, ok := strings.CutPrefix(line, "Exec="); ok {
					command_line = value
				}
			}
			command_line = strings.NewReplacer(`\\`, `\`, `\s`, " ", `\n`, "\n", `\r`, "\r", `\t`, "\t").Replace(command_line)
			got, err := shlex.Split(command_line)
			want := []string{copied_exe, "desktop-ui", "run-server"}
			if err != nil || !reflect.DeepEqual(got, want) {
				t.Fatalf("service argv: got %#v (%v), want %#v", got, err, want)
			}
		})
	}
}
