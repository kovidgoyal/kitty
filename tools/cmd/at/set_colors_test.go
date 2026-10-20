// License: GPLv3 Copyright: 2026, kitty contributors

package at

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSetColorsResetIgnoresArguments(t *testing.T) {
	missing_file := filepath.Join(t.TempDir(), "missing.conf")
	for _, reset := range []bool{false, true} {
		for _, test := range []struct {
			name, arg string
			invalid   bool
		}{
			{"invalid-color", "foreground=not-a-color", true},
			{"missing-file", missing_file, true},
			{"valid-color", "foreground=red", false},
		} {
			t.Run(fmt.Sprintf("%s/reset=%t", test.name, reset), func(t *testing.T) {
				payload := set_colors_json_type{}
				err := parse_colors_and_files([]string{test.arg}, options_set_colors_type{Reset: reset}, &payload)
				want_error := test.invalid && !reset
				if (err != nil) != want_error {
					t.Fatalf("expected error=%t, got: %v", want_error, err)
				}
				if err != nil {
					return
				}
				if payload.Reset != reset || payload.All != reset || payload.Configured != reset {
					t.Fatalf("reset=%t should set reset, all and configured to the same value, got: %#v", reset, payload)
				}
				if reset {
					if len(payload.Colors) != 0 {
						t.Fatalf("--reset did not ignore color arguments: %#v", payload.Colors)
					}
				} else if payload.Colors["foreground"] != uint32(0xff0000) {
					t.Fatalf("foreground was not parsed: %#v", payload.Colors)
				}
			})
		}
	}
}

func TestSetColorsConfFiles(t *testing.T) {
	tdir := t.TempDir()
	write := func(name string, lines ...string) string {
		path := filepath.Join(tdir, name)
		if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")), 0o600); err != nil {
			t.Fatal(err)
		}
		return path
	}
	write("base.conf", "selection_background #00ff00")
	good := write("good.conf",
		"# a comment",
		"foreground\t#ff0000",
		"  background   #0000ff",
		"font_size 12",
		"cursor none",
		"background_opacity 0.5",
		"wayland_titlebar_color background",
		"include base.conf",
		"color1 #"+strings.Repeat("a", 6)+" "+strings.Repeat(" ", 70000),
	)
	payload := set_colors_json_type{}
	if err := parse_colors_and_files([]string{good}, options_set_colors_type{}, &payload); err != nil {
		t.Fatal(err)
	}
	expected := map[string]any{
		"foreground": uint32(0xff0000), "background": uint32(0xff), "cursor": nil,
		"selection_background": uint32(0xff00), "color1": uint32(0xaaaaaa),
		"wayland_titlebar_color": 1,
	}
	if len(payload.Colors) != len(expected) {
		t.Fatalf("unexpected colors parsed from conf file: %#v", payload.Colors)
	}
	for k, v := range expected {
		if actual, found := payload.Colors[k]; !found || actual != v {
			t.Fatalf("%s: expected %#v got %#v", k, v, actual)
		}
	}

	bad := write("bad.conf", "background #000000", "foreground #zzzzzz")
	err := parse_colors_and_files([]string{bad}, options_set_colors_type{}, &set_colors_json_type{})
	if err == nil || !strings.Contains(err.Error(), "foreground") {
		t.Fatalf("expected an error for an invalid color in a conf file, got: %v", err)
	}
}

func TestSetColorsSpecialColors(t *testing.T) {
	for key := range special_colors {
		if special_color_values[key] == nil {
			t.Fatalf("The special values for %s are not defined", key)
		}
	}
	// expected values are from kitty.colors.parse_colors()
	for _, test := range []struct {
		arg      string
		expected int
	}{
		{"wayland_titlebar_color=#123456", 0x12345602},
		{"wayland_titlebar_color=system", 0},
		{`wayland_titlebar_color="background"`, 1},
		{"macos_titlebar_color=dark", -2},
		{"macos_titlebar_color=light", -1},
		{"macos_titlebar_color=background", 1},
		{"macos_titlebar_color=red", 0xff000002},
		{"scrollbar_handle_color=selection_background", 1},
		{"scrollbar_track_color=foreground", 0},
		{"scrollbar_track_color=#123456", 0x12345602},
	} {
		payload := set_colors_json_type{}
		if err := parse_colors_and_files([]string{test.arg}, options_set_colors_type{}, &payload); err != nil {
			t.Fatalf("%s: %s", test.arg, err)
		}
		key, _, _ := strings.Cut(test.arg, "=")
		if actual := payload.Colors[key]; actual != test.expected {
			t.Fatalf("%s: expected %#x got %#v", test.arg, test.expected, actual)
		}
	}
	for _, arg := range []string{"wayland_titlebar_color=light", "scrollbar_track_color=system", "macos_titlebar_color=none"} {
		if err := parse_colors_and_files([]string{arg}, options_set_colors_type{}, &set_colors_json_type{}); err == nil {
			t.Fatalf("%s: expected an error", arg)
		}
	}
}
