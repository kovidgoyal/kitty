// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// Keep in sync with kitty_tests/open_actions.py
const mime_cache_test_types = `
<mime-type type="text/x-kt-literal"><glob pattern="KittyLiteral"/></mime-type>
<mime-type type="text/x-kt-cs"><glob pattern="*.KCS" case-sensitive="true"/></mime-type>
<mime-type type="text/x-kt-ext"><glob pattern="*.kext"/><alias type="text/x-kt-old"/><alias type="application/x-kt-older"/></mime-type>
<mime-type type="text/x-kt-long"><glob pattern="*.long.kext"/></mime-type>
<mime-type type="text/x-kt-light"><glob pattern="*.kw" weight="40"/></mime-type>
<mime-type type="text/x-kt-heavy"><glob pattern="*.kw" weight="80"/></mime-type>
<mime-type type="text/x-kt-glob"><glob pattern="kglob[0-9].*"/></mime-type>
<mime-type type="text/x-kt-negated-glob"><glob pattern="kneg[!0-9].*"/></mime-type>
<mime-type type="text/x-kt-unicode"><glob pattern="*.kü"/></mime-type>
<mime-type type="application/json"><glob pattern="*.kjson"/><alias type="application/x-kt-json"/></mime-type>
<mime-type type="text/x-kt-make"><glob pattern="Makefile" case-sensitive="true"/></mime-type>
<mime-type type="text/x-kt-system"><glob pattern="*.kuser"/></mime-type>
`

func TestMimeCache(t *testing.T) {
	if _, err := exec.LookPath("update-mime-database"); err != nil {
		t.Skip("update-mime-database not available")
	}
	tdir := t.TempDir()
	build_cache := func(data_dir, types string) {
		pkgs := filepath.Join(data_dir, "mime", "packages")
		if err := os.MkdirAll(pkgs, 0o755); err != nil {
			t.Fatal(err)
		}
		xml := `<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">` + types + `</mime-info>`
		if err := os.WriteFile(filepath.Join(pkgs, "kitty-test.xml"), []byte(xml), 0o644); err != nil {
			t.Fatal(err)
		}
		cmd := exec.Command("update-mime-database", filepath.Join(data_dir, "mime"))
		cmd.Env = append(os.Environ(), "PKGSYSTEM_ENABLE_FSYNC=0")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("update-mime-database failed with error: %s and output:\n%s", err, out)
		}
	}
	user, system := filepath.Join(tdir, "user"), filepath.Join(tdir, "system")
	build_cache(system, mime_cache_test_types)
	build_cache(user, `<mime-type type="text/x-kt-user"><glob pattern="*.kuser"/><glob pattern="*.kext.override"/></mime-type><mime-type type="text/x-kt-ext"><alias type="text/x-kt-user-alias"/></mime-type>`)
	build_cache(filepath.Join(tdir, "ignored"), `<mime-type type="text/x-kt-ignored"><glob pattern="*.kuser"/></mime-type>`)

	t.Setenv("XDG_DATA_HOME", user)
	t.Setenv("XDG_DATA_DIRS", strings.Join([]string{"relative/dir", system + "/", tdir + "/missing", tdir + "/ignored"}, ":"))
	paths := mime_cache_paths()
	expected_paths := []string{
		filepath.Join(user, "mime", "mime.cache"), filepath.Join(system, "mime", "mime.cache"),
		filepath.Join(tdir, "missing", "mime", "mime.cache"), filepath.Join(tdir, "ignored", "mime", "mime.cache")}
	if strings.Join(paths, "\n") != strings.Join(expected_paths, "\n") {
		t.Fatalf("Incorrect mime.cache paths: %#v != %#v", expected_paths, paths)
	}
	caches := load_mime_caches(paths)
	if len(caches) != 3 {
		t.Fatalf("Expected to load 3 caches, loaded: %d", len(caches))
	}
	for name, expected := range map[string]string{
		"KittyLiteral":    "text/x-kt-literal",
		"kittyliteral":    "text/x-kt-literal",
		"KITTYLITERAL":    "text/x-kt-literal",
		"xKittyLiteral":   "",
		"a.KCS":           "text/x-kt-cs",
		"a.kcs":           "",
		"a.kext":          "text/x-kt-ext",
		"A.KEXT":          "text/x-kt-ext",
		"x.long.kext":     "text/x-kt-long",
		"x.LONG.KEXT":     "text/x-kt-long",
		"xlong.kext":      "text/x-kt-ext",
		"a.kw":            "text/x-kt-heavy",
		"kglob1.txt":      "text/x-kt-glob",
		"KGLOB1.TXT":      "text/x-kt-glob",
		"kglobx.txt":      "",
		"knegx.txt":       "text/x-kt-negated-glob",
		"kneg1.txt":       "",
		"a.kü":            "text/x-kt-unicode",
		"a.KÜ":            "text/x-kt-unicode",
		"a.kuser":         "text/x-kt-user",
		"a.kext.override": "text/x-kt-user",
		"":                "",
		"a\x00.kext":      "",
		"notmatched":      "",
	} {
		if actual := caches.lookup(name); actual != expected {
			t.Errorf("Incorrect MIME type for %#v: %#v != %#v", name, expected, actual)
		}
	}
	ext_names := []string{"text/x-kt-ext", "text/x-kt-user-alias", "application/x-kt-older", "text/x-kt-old"}
	for q, expected := range map[string][]string{
		"text/x-kt-ext":    ext_names,
		"text/x-kt-old":    ext_names,
		"application/json": {"application/json", "application/x-kt-json"},
		"unknown/x-kt":     {"unknown/x-kt"},
	} {
		if actual := caches.aliases(q); strings.Join(actual, " ") != strings.Join(expected, " ") {
			t.Errorf("Incorrect aliases for %#v: %#v != %#v", q, expected, actual)
		}
	}
	if actual := (mime_caches{}).aliases("text/x-kt-ext"); len(actual) != 1 || actual[0] != "text/x-kt-ext" {
		t.Errorf("Incorrect aliases with no caches: %#v", actual)
	}
	if _, err := load_mime_cache(filepath.Join(tdir, "missing", "mime", "mime.cache")); err == nil {
		t.Fatalf("Loading a non-existent cache did not fail")
	}
	bad := filepath.Join(tdir, "bad.cache")
	if err := os.WriteFile(bad, []byte(strings.Repeat("\x00", mime_cache_header_size)), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := load_mime_cache(bad); err == nil {
		t.Fatalf("Loading a cache with an invalid version did not fail")
	}
	truncated := filepath.Join(tdir, "truncated.cache")
	if data, err := os.ReadFile(filepath.Join(system, "mime", "mime.cache")); err != nil {
		t.Fatal(err)
	} else if err := os.WriteFile(truncated, data[:mime_cache_header_size+8], 0o644); err != nil {
		t.Fatal(err)
	}
	if c, err := load_mime_cache(truncated); err != nil {
		t.Fatal(err)
	} else if actual := (mime_caches{c}).lookup("a.kext"); actual != "" {
		t.Fatalf("Lookup in truncated cache returned: %#v", actual)
	}
}
