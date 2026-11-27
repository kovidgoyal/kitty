// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"bytes"
	"errors"
	"image/png"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

func write_test_file(t *testing.T, path, text string) string {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestIconLookup(t *testing.T) {
	tdir := t.TempDir()
	dirs := &XDGDirs{
		DataHome: filepath.Join(tdir, "home"), ConfigHome: filepath.Join(tdir, "config"), Home: filepath.Join(tdir, "user"),
		DataDirs: []string{filepath.Join(tdir, "sys")},
	}
	w := func(path, text string) string { return write_test_file(t, filepath.Join(tdir, path), text) }

	// Theme detection from config files
	w("config/gtk-3.0/settings.ini", "[Settings]\ngtk-icon-theme-name = \"GtkTheme\"\n")
	w("config/kdeglobals", "[General]\nTheme=wrong\n[Icons]\nTheme[$e]=KdeTheme\n")
	if q := dirs.icon_theme_from_config_files(); q != "GtkTheme" {
		t.Fatalf("Incorrect icon theme with no desktop: %#v", q)
	}
	dirs.CurrentDesktops = []string{"KDE"}
	if q := dirs.icon_theme_from_config_files(); q != "KdeTheme" {
		t.Fatalf("Incorrect icon theme on KDE: %#v", q)
	}

	if diff := cmp.Diff([]string{filepath.Join(tdir, "home", "icons"), filepath.Join(tdir, "user", ".icons"), filepath.Join(tdir, "sys", "icons")}, dirs.IconBaseDirs()); diff != "" {
		t.Fatalf("Incorrect icon base dirs:\n%s", diff)
	}

	// The theme's index.theme in the user's home has no Inherits and is
	// used for the directory list, the one in the system dir has Inherits
	w("home/icons/mytheme/index.theme", `[Icon Theme]
Name=My Theme
Directories=apps/16,apps/48,apps/48@2x,apps/scalable
[apps/16]
Size=16
Type=Fixed
[apps/48]
Size=48
Type=Fixed
[apps/48@2x]
Size=48
Scale=2
Type=Fixed
[apps/scalable]
Size=64
MinSize=64
MaxSize=256
Type=Scalable
`)
	w("sys/icons/mytheme/index.theme", "[Icon Theme]\nInherits=parent\nDirectories=ignored\n[ignored]\nSize=48\n")
	w("sys/icons/parent/index.theme", "[Icon Theme]\nInherits=hicolor\nDirectories=apps\n[apps]\nSize=32\n")
	w("sys/icons/hicolor/index.theme", "[Icon Theme]\nDirectories=48x48/apps\n[48x48/apps]\nSize=48\nType=Threshold\n")
	small := w("home/icons/mytheme/apps/16/app.png", "")
	medium := w("sys/icons/mytheme/apps/48/app.png", "")
	medium_svg := w("sys/icons/mytheme/apps/48/app.svg", "")
	large := w("home/icons/mytheme/apps/48@2x/app.png", "")
	scalable := w("sys/icons/mytheme/apps/scalable/app.svg", "")
	w("sys/icons/mytheme/ignored/app.png", "")
	only_small := w("home/icons/mytheme/apps/16/small-only.png", "")
	from_parent := w("sys/icons/parent/apps/inherited.svg", "")
	from_hicolor := w("sys/icons/hicolor/48x48/apps/hc.png", "")
	from_hicolor_masked := w("sys/icons/hicolor/48x48/apps/app.png", "")
	from_pixmaps := w("sys/pixmaps/legacy.xpm", "")
	w("sys/pixmaps/inherited.png", "")
	absolute := w("abs/icon.svg", "")

	names := func(themes []icon_theme) (ans []string) {
		for _, x := range themes {
			ans = append(ans, x.name)
		}
		return
	}
	if diff := cmp.Diff([]string{"mytheme", "parent", "hicolor"}, names(dirs.themes_to_search("mytheme"))); diff != "" {
		t.Fatalf("Incorrect themes to search:\n%s", diff)
	}
	if diff := cmp.Diff([]string{"hicolor"}, names(dirs.themes_to_search("nonexistent"))); diff != "" {
		t.Fatalf("Incorrect themes to search for a missing theme:\n%s", diff)
	}

	all_names := []string{"app", "app.png", "small-only", "inherited", "hc", "legacy", absolute, "/nonexistent/x.png", "missing", ""}
	for _, tc := range []struct {
		theme    string
		px       int
		expected map[string]string
	}{
		{"mytheme", 48, map[string]string{"app": medium, "app.png": medium}},
		{"mytheme", 16, map[string]string{"app": small}},
		{"mytheme", 128, map[string]string{"app": scalable}},
		// Both apps/48@2x and apps/scalable match exactly, the first in Directories wins
		{"mytheme", 96, map[string]string{"app": large}},
		// No exact match, downscaling from 64 beats upscaling from 48
		{"mytheme", 56, map[string]string{"app": scalable}},
		{"mytheme", 512, map[string]string{"app": scalable}},
		{"nonexistent", 48, map[string]string{"small-only": "", "app": from_hicolor_masked, "app.png": from_hicolor_masked, "inherited": filepath.Join(tdir, "sys/pixmaps/inherited.png")}},
	} {
		expected := map[string]string{
			"small-only": only_small, "inherited": from_parent, "hc": from_hicolor, "legacy": from_pixmaps, absolute: absolute,
		}
		for k, v := range tc.expected {
			if v == "" {
				delete(expected, k)
			} else {
				expected[k] = v
			}
		}
		if _, found := tc.expected["app.png"]; !found {
			expected["app.png"] = expected["app"]
		}
		if diff := cmp.Diff(expected, dirs.FindIcons(tc.theme, tc.px, all_names...)); diff != "" {
			t.Errorf("Incorrect icons for theme %s at size %d:\n%s", tc.theme, tc.px, diff)
		}
	}
	_ = medium_svg

	for _, theme := range []string{"breeze", "breeze-dark", "Papirus", "Papirus-Dark", "papirus-dark", "foo", "foobar-dark", "foo-darkish", "Yaru", "Yaru_dark"} {
		w("sys/icons/"+theme+"/index.theme", "[Icon Theme]\n")
	}
	if err := os.MkdirAll(filepath.Join(tdir, "sys/icons/nothing-dark"), 0o755); err != nil {
		t.Fatal(err)
	}
	w("sys/icons/nothing/index.theme", "[Icon Theme]\n")
	for _, tc := range []struct {
		theme, dark, light string
	}{
		{"breeze", "breeze-dark", "breeze"},
		{"breeze-dark", "breeze-dark", "breeze"},
		{"Papirus", "Papirus-Dark", "Papirus"},
		{"papirus-dark", "papirus-dark", "Papirus"},
		{"Yaru", "Yaru_dark", "Yaru"},
		{"Yaru_dark", "Yaru_dark", "Yaru"},
		{"foo", "foo", "foo"},
		{"foobar-dark", "foobar-dark", "foobar-dark"},
		{"nothing", "nothing", "nothing"},
		{"nothing-dark", "nothing-dark", "nothing"},
		{"dark", "dark", "dark"},
		{"", "", ""},
	} {
		if q := dirs.IconThemeForBackground(tc.theme, true); q != tc.dark {
			t.Errorf("Incorrect dark variant of %#v: %#v != %#v", tc.theme, tc.dark, q)
		}
		if q := dirs.IconThemeForBackground(tc.theme, false); q != tc.light {
			t.Errorf("Incorrect light variant of %#v: %#v != %#v", tc.theme, tc.light, q)
		}
	}
}

func TestIconRendering(t *testing.T) {
	tdir := t.TempDir()
	cache_dir := filepath.Join(tdir, "cache")
	r := NewIconRenderer(cache_dir)
	if p, err := r.Render("/some/icon.PNG", 32); err != nil || p != "/some/icon.PNG" {
		t.Fatalf("PNG icon was not used directly: %#v %v", p, err)
	}
	svg := write_test_file(t, filepath.Join(tdir, "icon.svg"), `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="20"><rect width="10" height="20" fill="red"/></svg>`)
	bad := write_test_file(t, filepath.Join(tdir, "bad.svg"), "not an svg")

	none := NewIconRenderer(cache_dir)
	none.rsvg_convert, none.magick = "", ""
	if _, err := none.Render(svg, 32); !errors.Is(err, ErrNoRasterizer) {
		t.Fatalf("Rendering with no rasterizer did not fail correctly: %v", err)
	}
	if r.rsvg_convert == "" && r.magick == "" {
		t.Skip("Neither rsvg-convert nor ImageMagick available")
	}
	p, err := r.Render(svg, 32)
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Dir(p) != cache_dir {
		t.Fatalf("Rendered icon not in cache dir: %s", p)
	}
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	cfg, err := png.DecodeConfig(bytes.NewReader(data))
	if err != nil {
		t.Fatalf("Rendered icon is not a valid PNG: %s", err)
	}
	if cfg.Height != 32 || cfg.Width != 16 {
		t.Fatalf("Rendered icon has incorrect size: %dx%d", cfg.Width, cfg.Height)
	}
	if p2, err := none.Render(svg, 32); err == nil {
		t.Fatalf("Rendering with no rasterizer did not fail even though cached: %s", p2)
	}
	// A cached result is used without re-rendering
	r2 := NewIconRenderer(cache_dir)
	r2.rsvg_convert, r2.magick = "/nonexistent/rsvg", ""
	if p2, err := r2.Render(svg, 32); err != nil || p2 != p {
		t.Fatalf("Cached icon not used: %#v %v", p2, err)
	}
	if p2, err := r.Render(svg, 64); err != nil || p2 == p {
		t.Fatalf("Icon at a different size not rendered separately: %#v %v", p2, err)
	}
	if r.magick != "" {
		only_magick := NewIconRenderer(filepath.Join(tdir, "magick-cache"))
		only_magick.rsvg_convert = ""
		mp, err := only_magick.Render(svg, 20)
		if err != nil {
			t.Fatal(err)
		}
		data, err := os.ReadFile(mp)
		if err != nil {
			t.Fatal(err)
		}
		if cfg, err := png.DecodeConfig(bytes.NewReader(data)); err != nil || cfg.Height != 20 || cfg.Width != 10 {
			t.Fatalf("Icon rendered by ImageMagick is invalid: %#v %v", cfg, err)
		}
	}
	if _, err = r.Render(bad, 32); err == nil {
		t.Fatalf("Rendering an invalid SVG did not fail")
	}
	if _, err = r.Render(bad, 32); err == nil || !strings.Contains(err.Error(), "failed previously") {
		t.Fatalf("Failure was not cached: %v", err)
	}
	entries, err := os.ReadDir(cache_dir)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".tmp") {
			t.Fatalf("Temporary file left in cache: %s", e.Name())
		}
	}
}
