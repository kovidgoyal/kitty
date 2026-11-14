// License: GPLv3 Copyright: 2026, datty contributors

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
		{"/opt/datty/daddy", `/opt/datty/daddy a`},
		{"/opt/datty app/daddy", `'/opt/datty app/daddy' a`},
		{"/opt/datty'app/daddy", `'/opt/datty'"'"'app/daddy' a`},
		{`/opt/datty"app/daddy`, `'/opt/datty"app/daddy' a`},
		{`/opt/datty\app/daddy`, `'/opt/datty\\app/daddy' a`},
		{"/opt/datty$app/daddy", `'/opt/datty$app/daddy' a`},
		{"/opt/datty\tapp/daddy", `'/opt/datty\tapp/daddy' a`},
		{"/opt/datty\napp/daddy", `'/opt/datty\napp/daddy' a`},
	} {
		got, err := dbus_service_exec_line(tc.exe, "a")
		if err != nil {
			t.Fatalf("Unexpected error for %#v: %s", tc.exe, err)
		}
		if got != tc.want {
			t.Fatalf("Exec line for %#v: got %#v want %#v", tc.exe, got, tc.want)
		}
	}
	if _, err := dbus_service_exec_line("/opt/datty\rapp/daddy"); err == nil {
		t.Fatalf("No error for path containing a carriage return")
	}
}
