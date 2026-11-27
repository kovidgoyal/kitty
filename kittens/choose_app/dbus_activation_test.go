// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"bufio"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/dbus"
)

func TestDBusNames(t *testing.T) {
	for name, valid := range map[string]bool{
		"org.gnome.Nautilus": true, "com.mitchellh.ghostty": true, "org.example.my-app": true, "a.b": true,
		"nautilus": false, "org..x": false, "org.1x": false, "org.x y": false, ".org.x": false, "org.x.": false, "": false,
		strings.Repeat("a.", 128) + "b": false,
	} {
		if is_valid_bus_name(name) != valid {
			t.Errorf("Validity of the bus name %#v is not %v", name, valid)
		}
	}
	if p := dbus_object_path("org.example.my-app"); p != "/org/example/my_app" || !p.IsValid() {
		t.Fatalf("Incorrect object path: %s", p)
	}
	t.Setenv("DESKTOP_STARTUP_ID", "")
	values := func(m map[string]dbus.Variant) map[string]any {
		ans := map[string]any{}
		for k, v := range m {
			ans[k] = v.Value()
		}
		return ans
	}
	if diff := cmp.Diff(map[string]any{"activation-token": "tok", "desktop-startup-id": "tok"}, values(platform_data("tok"))); diff != "" {
		t.Fatalf("Incorrect platform data:\n%s", diff)
	}
	t.Setenv("DESKTOP_STARTUP_ID", "x11-id")
	if diff := cmp.Diff(map[string]any{"activation-token": "tok", "desktop-startup-id": "x11-id"}, values(platform_data("tok"))); diff != "" {
		t.Fatalf("Incorrect platform data with a startup id:\n%s", diff)
	}
	t.Setenv("DESKTOP_STARTUP_ID", "")
	if len(platform_data("")) != 0 {
		t.Fatalf("Platform data without a token is not empty")
	}
}

func TestDBusLaunching(t *testing.T) {
	tdir := t.TempDir()
	w := func(path, text string) { write_test_file(t, filepath.Join(tdir, path), text) }
	app := func(extra string) string { return "[Desktop Entry]\nType=Application\nName=App\n" + extra }
	w("sys/applications/org.example.WithExec.desktop", app("DBusActivatable=true\nExec=withexec %F\n"))
	w("sys/applications/org.example.NoExec.desktop", app("DBusActivatable=true\n"))
	w("sys/applications/invalid-name.desktop", app("DBusActivatable=true\n"))
	w("sys/applications/invalid-name-exec.desktop", app("DBusActivatable=true\nExec=fallback %f\n"))
	db := new_app_database(&XDGDirs{
		DataHome: filepath.Join(tdir, "home"), ConfigHome: filepath.Join(tdir, "config"),
		DataDirs: []string{filepath.Join(tdir, "sys")},
	}, func(m string) []string { return []string{m} })
	// Applications without Exec are usable only if they have a valid bus name
	if db.AppByID("org.example.NoExec") == nil || db.AppByID("invalid-name") != nil || db.AppByID("invalid-name-exec") == nil {
		t.Fatalf("Incorrect handling of D-Bus activatable applications without Exec")
	}
	settings, err := settings_from_config(NewConfig())
	if err != nil {
		t.Fatal(err)
	}
	type activation struct {
		Name, Token string
		URIs        []string
	}
	var activations []activation
	var runs [][]string
	var activate_err error
	l := launchers{
		run: func(argv []string, cwd string, env []string) error { runs = append(runs, argv); return nil },
		activate: func(name string, uris []string, token string) error {
			activations = append(activations, activation{name, token, uris})
			return activate_err
		},
	}
	reset := func() { activations, runs, activate_err = nil, nil, nil }
	targets := []Target{{Path: "/a b.txt"}, {URL: "https://example.com"}}

	// Started via D-Bus, with all files at once and the token
	if err = launch(settings, db, ChoiceForDesktopID("org.example.WithExec"), targets, "tok", l); err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]activation{{"org.example.WithExec", "tok", []string{"file:///a%20b.txt", "https://example.com"}}}, activations); diff != "" || len(runs) != 0 {
		t.Fatalf("Incorrect D-Bus activation: %v\n%s", runs, diff)
	}
	// Without a token from asking, the one from the environment is used
	reset()
	t.Setenv("XDG_ACTIVATION_TOKEN", "env-tok")
	if err = launch(settings, db, ChoiceForDesktopID("org.example.NoExec"), nil, "", l); err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]activation{{"org.example.NoExec", "env-tok", []string{}}}, activations); diff != "" {
		t.Fatalf("Incorrect activation without files:\n%s", diff)
	}
	// Failure falls back to Exec, if any
	reset()
	activate_err = errors.New("no such service")
	if err = launch(settings, db, ChoiceForDesktopID("org.example.WithExec"), targets[:1], "", l); err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([][]string{{"withexec", "/a b.txt"}}, runs); diff != "" {
		t.Fatalf("No fallback to Exec:\n%s", diff)
	}
	reset()
	activate_err = errors.New("no such service")
	if err = launch(settings, db, ChoiceForDesktopID("org.example.NoExec"), targets[:1], "", l); err == nil || !strings.Contains(err.Error(), "no such service") {
		t.Fatalf("Activation failure without Exec not reported: %v", err)
	}
	// Invalid bus names use Exec directly
	reset()
	if err = launch(settings, db, ChoiceForDesktopID("invalid-name-exec"), targets[:1], "", l); err != nil {
		t.Fatal(err)
	}
	if len(activations) != 0 || len(runs) != 1 {
		t.Fatalf("Application with an invalid bus name not run with Exec: %v %v", activations, runs)
	}
}

type test_application struct {
	mutex sync.Mutex
	calls []string
}

func (a *test_application) Open(uris []string, platform_data map[string]dbus.Variant) *dbus.Error {
	a.mutex.Lock()
	defer a.mutex.Unlock()
	tok, _ := platform_data["activation-token"].Value().(string)
	a.calls = append(a.calls, "open "+strings.Join(uris, " ")+" token="+tok)
	return nil
}

func (a *test_application) Activate(platform_data map[string]dbus.Variant) *dbus.Error {
	a.mutex.Lock()
	defer a.mutex.Unlock()
	tok, _ := platform_data["activation-token"].Value().(string)
	a.calls = append(a.calls, "activate token="+tok)
	return nil
}

// TestDBusActivationOverBus runs a private session bus and an application on
// it, to check the actual D-Bus calls
func TestDBusActivationOverBus(t *testing.T) {
	daemon, err := exec.LookPath("dbus-daemon")
	if err != nil {
		t.Skip("dbus-daemon not available")
	}
	tdir := t.TempDir()
	cfg := filepath.Join(tdir, "session.conf")
	if err = os.WriteFile(cfg, []byte(`<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>session</type><listen>unix:dir=`+tdir+`</listen>
<policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/><allow own="*"/></policy></busconfig>`), 0o644); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(daemon, "--config-file="+cfg, "--nofork", "--print-address=1")
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err = cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = cmd.Process.Kill(); _ = cmd.Wait() }()
	address, err := bufio.NewReader(stdout).ReadString('\n')
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("DBUS_SESSION_BUS_ADDRESS", strings.TrimSpace(address))
	t.Setenv("DESKTOP_STARTUP_ID", "")

	conn, err := dbus.ConnectSessionBus()
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	const name = "net.kovidgoyal.kitty.test-app"
	app := &test_application{}
	if err = conn.Export(app, dbus_object_path(name), dbus_application_interface); err != nil {
		t.Fatal(err)
	}
	if reply, err := conn.RequestName(name, dbus.NameFlagDoNotQueue); err != nil || reply != dbus.RequestNameReplyPrimaryOwner {
		t.Fatalf("Could not own the bus name: %v %v", reply, err)
	}
	if err = dbus_activate(name, []string{"file:///x", "https://example.com"}, "tok"); err != nil {
		t.Fatal(err)
	}
	if err = dbus_activate(name, nil, ""); err != nil {
		t.Fatal(err)
	}
	app.mutex.Lock()
	calls := app.calls
	app.mutex.Unlock()
	if diff := cmp.Diff([]string{"open file:///x https://example.com token=tok", "activate token="}, calls); diff != "" {
		t.Fatalf("Incorrect calls to the application:\n%s", diff)
	}
	// An application that is not running and cannot be started
	if err = dbus_activate("net.kovidgoyal.kitty.not-installed", nil, ""); err == nil {
		t.Fatalf("Activating an application that does not exist did not fail")
	}
}
