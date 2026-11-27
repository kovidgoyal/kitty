// License: GPLv3 Copyright: 2026, kitty contributors

package desktop_ui

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/dbus"
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

func TestDBusServiceExecLine(t *testing.T) {
	for _, tc := range []struct{ exe, want string }{
		{"/opt/kitty/kitten", `/opt/kitty/kitten a`},
		{"/opt/kitty app/kitten", `'/opt/kitty app/kitten' a`},
		{"/opt/kitty'app/kitten", `'/opt/kitty'"'"'app/kitten' a`},
		{`/opt/kitty"app/kitten`, `'/opt/kitty"app/kitten' a`},
		{`/opt/kitty\app/kitten`, `'/opt/kitty\\app/kitten' a`},
		{"/opt/kitty$app/kitten", `'/opt/kitty$app/kitten' a`},
		{"/opt/kitty\tapp/kitten", `'/opt/kitty\tapp/kitten' a`},
		{"/opt/kitty\napp/kitten", `'/opt/kitty\napp/kitten' a`},
	} {
		got, err := dbus_service_exec_line(tc.exe, "a")
		if err != nil {
			t.Fatalf("Unexpected error for %#v: %s", tc.exe, err)
		}
		if got != tc.want {
			t.Fatalf("Exec line for %#v: got %#v want %#v", tc.exe, got, tc.want)
		}
	}
	if _, err := dbus_service_exec_line("/opt/kitty\rapp/kitten"); err == nil {
		t.Fatalf("No error for path containing a carriage return")
	}
}

func TestAppChooser(t *testing.T) {
	args := choose_app_args(ChooseAppData{
		Choices: []string{"org.kde.okular", "firefox"}, LastChoice: "firefox", Filename: "report.pdf", Uri: "file:///x/report.pdf",
	}, "/out", "/pid")
	want := []string{
		"choose-app", "--output-format=json", "--write-output-to", "/out", "--write-pid-to", "/pid", "--commands-as-desktop-files",
		"--title", "Open with", "--content-type", "application/pdf", "--display-name", "report.pdf",
		"--recommend", "org.kde.okular", "--recommend", "firefox", "--preselect", "firefox",
	}
	if diff := cmp.Diff(want, args); diff != "" {
		t.Fatalf("Incorrect choose-app arguments:\n%s", diff)
	}
	args = choose_app_args(ChooseAppData{ContentType: "x-scheme-handler/https", Uri: "https://example.com"}, "/out", "/pid")
	if diff := cmp.Diff([]string{"--content-type", "x-scheme-handler/https", "--display-name", "https://example.com"}, args[len(args)-4:]); diff != "" {
		t.Fatalf("Incorrect choose-app arguments for URL:\n%s", diff)
	}

	for _, tc := range []struct {
		output, token string
		response      uint32
		results       vmap
	}{
		{`{"choice": {"desktop_id": "org.kde.okular.desktop"}, "remember": true}`, "", RESPONSE_SUCCESS, vmap{"choice": dbus.MakeVariant("org.kde.okular")}},
		{`{"choice": {"desktop_id": "firefox.desktop"}}`, "tok", RESPONSE_SUCCESS, vmap{"choice": dbus.MakeVariant("firefox"), "activation_token": dbus.MakeVariant("tok")}},
		{`{"interrupted": true}`, "", RESPONSE_CANCELED, nil},
		{`{"error": "boom"}`, "", RESPONSE_ENDED, nil},
		{`{"choice": {"cmdline": ["x"]}}`, "", RESPONSE_ENDED, nil},
		{`garbage`, "", RESPONSE_ENDED, nil},
	} {
		response, results := parse_app_chooser_response([]byte(tc.output), tc.token)
		if response != tc.response || !reflect.DeepEqual(results, tc.results) {
			t.Errorf("Incorrect response for %s: %d %v", tc.output, response, results)
		}
	}

	for spec, want := range map[string][3]string{
		"":         {"center", "", ""},
		"25 80":    {"center-sized", "25", "80"},
		" 30  100": {"center-sized", "30", "100"},
		"5 80":     {"center", "", ""},
		"x 80":     {"center", "", ""},
		"25":       {"center", "", ""},
	} {
		edge, lines, columns := panel_size("test", spec)
		if got := [3]string{edge, lines, columns}; got != want {
			t.Errorf("Incorrect panel size for %#v: %v != %v", spec, got, want)
		}
	}

	patched := string(patch_portals_conf([]byte("[preferred]\ndefault=gtk\norg.freedesktop.impl.portal.AppChooser=gnome\n")))
	if !strings.Contains(patched, APP_CHOOSER_INTERFACE+"=kitty;*") || strings.Contains(patched, "AppChooser=gnome") || !strings.Contains(patched, "default=gtk") {
		t.Fatalf("Incorrectly patched portals.conf:\n%s", patched)
	}
}

func TestIconThemeSetting(t *testing.T) {
	tdir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", tdir)
	t.Setenv("XDG_CURRENT_DESKTOP", "")
	read := func(opts *Config) (string, bool) {
		p, err := NewPortal(opts, nil)
		if err != nil {
			t.Fatal(err)
		}
		v, derr := p.Read(PORTAL_INTERFACE_NAMESPACE, PORTAL_ICON_THEME_KEY)
		if derr != nil {
			return "", false
		}
		var ans string
		if err := v.Store(&ans); err != nil {
			t.Fatal(err)
		}
		return ans, true
	}
	if theme, found := read(NewConfig()); found {
		t.Fatalf("Icon theme provided when none is configured: %#v", theme)
	}
	if err := os.MkdirAll(filepath.Join(tdir, "gtk-3.0"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(tdir, "gtk-3.0", "settings.ini"), []byte("[Settings]\ngtk-icon-theme-name=Papirus\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if theme, _ := read(NewConfig()); theme != "Papirus" {
		t.Fatalf("Icon theme not read from the GTK settings: %#v", theme)
	}
	opts := NewConfig()
	if err := opts.Parse("icon_theme", "breeze"); err != nil {
		t.Fatal(err)
	}
	if theme, _ := read(opts); theme != "breeze" {
		t.Fatalf("Icon theme setting not used: %#v", theme)
	}
}

func TestSettingsCanary(t *testing.T) {
	p, err := NewPortal(NewConfig(), nil)
	if err != nil {
		t.Fatal(err)
	}
	all, _ := p.ReadAll(nil)
	if !has_settings_canary(all) {
		t.Fatalf("Settings from this kitten not detected: %v", all)
	}
	filtered, _ := p.ReadAll([]string{PORTAL_APPEARANCE_NAMESPACE})
	if has_settings_canary(filtered) {
		t.Fatalf("Canary detected in settings that do not include it: %v", filtered)
	}
	if has_settings_canary(ReadAllType{SETTINGS_CANARY_NAMESPACE: {}}) || has_settings_canary(nil) {
		t.Fatalf("Canary detected without the canary key")
	}
}
