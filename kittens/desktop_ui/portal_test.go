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
