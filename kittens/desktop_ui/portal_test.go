// License: GPLv3 Copyright: 2026, kitty contributors

package desktop_ui

import (
	"testing"
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
