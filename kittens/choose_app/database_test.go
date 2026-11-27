// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestDesktopEntryParsing(t *testing.T) {
	for locale, expected := range map[string][]string{
		"":                       nil,
		"C":                      nil,
		"en_US.UTF-8":            {"en_US", "en"},
		"sr_YU@Latn":             {"sr_YU@Latn", "sr_YU", "sr@Latn", "sr"},
		"de":                     {"de"},
		"de_DE.ISO-8859-1@euro":  {"de_DE@euro", "de_DE", "de@euro", "de"},
		"pt_BR.UTF-8@something=": {"pt_BR@something=", "pt_BR", "pt@something=", "pt"},
	} {
		if diff := cmp.Diff(expected, locale_candidates(locale)); diff != "" {
			t.Errorf("Incorrect locale candidates for %#v:\n%s", locale, diff)
		}
	}
	t.Setenv("LC_ALL", "")
	t.Setenv("LC_MESSAGES", "")
	t.Setenv("LANG", "de_DE.UTF-8")
	t.Setenv("LANGUAGE", "fr_CA:de")
	if diff := cmp.Diff([]string{"fr_CA", "fr", "de", "de_DE"}, CurrentLocales()); diff != "" {
		t.Errorf("Incorrect current locales:\n%s", diff)
	}
	t.Setenv("LANG", "C")
	if ans := CurrentLocales(); ans != nil {
		t.Errorf("LANGUAGE not ignored for the C locale: %#v", ans)
	}

	for val, expected := range map[string][]string{
		"a;b;c;":        {"a", "b", "c"},
		"a;b":           {"a", "b"},
		`a\;b;c`:        {"a;b", "c"},
		`a\sb;c\\;`:     {"a b", `c\`},
		";;":            nil,
		"":              nil,
		"image/png;x/y": {"image/png", "x/y"},
	} {
		if diff := cmp.Diff(expected, parse_list(val)); diff != "" {
			t.Errorf("Incorrect list for %#v:\n%s", val, diff)
		}
	}

	e, err := ParseDesktopEntry(strings.NewReader(`
# comment
[Desktop Entry]
Type=Application
Name=Viewer
Name[de]=Betrachter
Name[de_DE]=Bildbetrachter
Name[fr]=Visionneuse
GenericName = Image\sViewer
Keywords=photo;picture;
Keywords[de]=Foto;Bild;
Exec=viewer %F
Icon=viewer
Terminal=true
NoDisplay=false
MimeType=image/png;image/jpeg;
OnlyShowIn=KDE;GNOME;

[Desktop Action new]
Name=Should not be used
Exec=other
`), []string{"de_DE", "de"})
	if err != nil {
		t.Fatal(err)
	}
	expected := &DesktopEntry{
		Name: "Bildbetrachter", GenericName: "Image Viewer", Keywords: []string{"Foto", "Bild"}, Exec: "viewer %F", Icon: "viewer",
		Terminal: true, MimeTypes: []string{"image/png", "image/jpeg"}, OnlyShowIn: []string{"KDE", "GNOME"}, entry_type: true,
	}
	if diff := cmp.Diff(expected, e, cmp.AllowUnexported(DesktopEntry{})); diff != "" {
		t.Fatalf("Incorrect desktop entry:\n%s", diff)
	}
	if !e.ShouldShow([]string{"kde"}) || e.ShouldShow([]string{"XFCE"}) || e.ShouldShow(nil) {
		t.Fatalf("OnlyShowIn not respected")
	}
	e.OnlyShowIn, e.NotShowIn = nil, []string{"XFCE"}
	if e.ShouldShow([]string{"Budgie", "XFCE"}) || !e.ShouldShow([]string{"KDE"}) {
		t.Fatalf("NotShowIn not respected")
	}
	if _, err := ParseDesktopEntry(strings.NewReader("[Other]\nName=x\n"), nil); err == nil {
		t.Fatalf("Parsing a file without a [Desktop Entry] group did not fail")
	}
}

func TestDesktopEntryExec(t *testing.T) {
	for exec, expected := range map[string][]string{
		`a b  c`:                 {"a", "b", "c"},
		`"/opt/my app/x" --flag`: {"/opt/my app/x", "--flag"},
		"sh -c \"echo \\\"\\$HOME\\\" \\\\ \\` x\"": {"sh", "-c", "echo \"$HOME\" \\ ` x"},
		`x ""`:   {"x", ""},
		`x a\ b`: {"x", "a b"},
	} {
		toks, err := tokenize_exec(exec)
		if err != nil {
			t.Fatalf("Failed to tokenize %#v with error: %s", exec, err)
		}
		actual := make([]string, len(toks))
		for i, tok := range toks {
			actual[i] = tok.text
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Errorf("Incorrect tokenization of %#v:\n%s", exec, diff)
		}
	}
	if _, err := tokenize_exec(`x "unterminated`); err == nil {
		t.Fatalf("Unterminated quote did not fail")
	}

	f1, f2 := Target{Path: "/a b/1.png"}, Target{Path: "/x/2.png"}
	u := Target{URL: "https://example.com/x?y=1"}
	d := &DesktopEntry{ID: "test.desktop", Name: "Test App", Icon: "test-icon", Path: "/usr/share/applications/test.desktop"}
	for _, tc := range []struct {
		exec     string
		targets  []Target
		expected [][]string
	}{
		{"app %F", []Target{f1, f2}, [][]string{{"app", f1.Path, f2.Path}}},
		{"app %U", []Target{f1, u}, [][]string{{"app", "file:///a%20b/1.png", u.URL}}},
		{"app %f", []Target{f1, f2}, [][]string{{"app", f1.Path}, {"app", f2.Path}}},
		{"app %u", []Target{u}, [][]string{{"app", u.URL}}},
		{"app --file=%f", []Target{f1}, [][]string{{"app", "--file=" + f1.Path}}},
		{"app", []Target{f1, f2}, [][]string{{"app", f1.Path}, {"app", f2.Path}}},
		{"app %F", nil, [][]string{{"app"}}},
		{"app %f", nil, [][]string{{"app"}}},
		{"app %i %c %k 100%% %d %F", []Target{f1}, [][]string{{"app", "--icon", "test-icon", "Test App", d.Path, "100%", "", f1.Path}}},
		{`"%f"`, []Target{f1}, [][]string{{f1.Path}}},
	} {
		d.Exec = tc.exec
		actual, err := d.Commands(tc.targets...)
		if err != nil {
			t.Fatalf("Failed to expand %#v with error: %s", tc.exec, err)
		}
		if diff := cmp.Diff(tc.expected, actual); diff != "" {
			t.Errorf("Incorrect commands for %#v with targets %v:\n%s", tc.exec, tc.targets, diff)
		}
	}
	d.Exec = "%f"
	if _, err := d.Commands(); err == nil {
		t.Fatalf("Exec line with no program did not fail")
	}

	tdir := t.TempDir()
	odd := filepath.Join(tdir, "a:b.txt")
	if err := os.WriteFile(odd, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(tdir); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = os.Chdir(cwd) }()
	for q, expected := range map[string]Target{
		"a:b.txt":                  {Path: odd},
		"rel.txt":                  {Path: filepath.Join(tdir, "rel.txt")},
		"file:///x%20y/z":          {Path: "/x y/z"},
		"file://localhost/x":       {Path: "/x"},
		"https://example.com/a":    {URL: "https://example.com/a"},
		"mailto:someone@somewhere": {URL: "mailto:someone@somewhere"},
	} {
		actual, err := NewTarget(q)
		if err != nil {
			t.Fatalf("Failed to create target for %#v with error: %s", q, err)
		}
		if actual != expected {
			t.Errorf("Incorrect target for %#v: %#v != %#v", q, expected, actual)
		}
	}
	for _, q := range []string{"", "file://remote/x"} {
		if _, err := NewTarget(q); err == nil {
			t.Errorf("Creating target for %#v did not fail", q)
		}
	}
}

func TestAppDatabase(t *testing.T) {
	tdir := t.TempDir()
	write := func(path, text string) {
		path = filepath.Join(tdir, path)
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	app := func(name, exec, extra string) string {
		return "[Desktop Entry]\nType=Application\nName=" + name + "\nExec=" + exec + "\n" + extra
	}
	write("home/applications/viewer.desktop", app("Viewer", "viewer %f", "MimeType=image/png;\n"))
	write("sys/applications/viewer.desktop", app("System Viewer", "sysviewer %f", "MimeType=image/png;\n"))
	write("sys/applications/masked.desktop", app("Masked", "masked", "MimeType=image/png;\n"))
	write("home/applications/masked.desktop", app("Masked", "masked", "Hidden=true\n"))
	write("sys/applications/editor.desktop", app("Editor", "editor %F", "MimeType=text/plain;image/png;\n"))
	write("sys/applications/kde/okular.desktop", app("Okular", "okular %U", "MimeType=application/pdf;\n"))
	write("sys/applications/hidden-from-menus.desktop", app("Helper", "helper %f", "NoDisplay=true\nMimeType=text/x-special;\n"))
	write("sys/applications/missing.desktop", app("Missing", "missing", "TryExec=/nonexistent/kitty-test-exe\nMimeType=image/png;\n"))
	write("sys/applications/link.desktop", "[Desktop Entry]\nType=Link\nName=Link\nURL=https://example.com\n")
	write("sys/applications/broken.desktop", "garbage\n")
	write("sys/applications/browser.desktop", app("Browser", "browser %u", "MimeType=x-scheme-handler/https;text/html;\n"))
	write("config/kde-mimeapps.list", "[Default Applications]\nimage/png=missing.desktop;editor.desktop;\n")
	write("config/mimeapps.list", `[Default Applications]
image/png=viewer.desktop
text/plain=editor.desktop
[Added Associations]
application/pdf=browser.desktop;
[Removed Associations]
image/png=editor.desktop;
`)
	write("sys/applications/mimeapps.list", `[Added Associations]
image/png=editor.desktop;kde-okular.desktop;
text/plain=browser.desktop;
`)
	dirs := &XDGDirs{
		DataHome: filepath.Join(tdir, "home"), ConfigHome: filepath.Join(tdir, "config"),
		DataDirs: []string{filepath.Join(tdir, "sys")}, ConfigDirs: []string{filepath.Join(tdir, "etc")},
		CurrentDesktops: []string{"KDE"},
	}
	if diff := cmp.Diff([]string{
		filepath.Join(tdir, "config", "kde-mimeapps.list"), filepath.Join(tdir, "config", "mimeapps.list"),
		filepath.Join(tdir, "etc", "kde-mimeapps.list"), filepath.Join(tdir, "etc", "mimeapps.list"),
		filepath.Join(tdir, "home", "applications", "kde-mimeapps.list"), filepath.Join(tdir, "home", "applications", "mimeapps.list"),
		filepath.Join(tdir, "sys", "applications", "kde-mimeapps.list"), filepath.Join(tdir, "sys", "applications", "mimeapps.list"),
	}, dirs.MimeAppsListFiles()); diff != "" {
		t.Fatalf("Incorrect mimeapps.list files:\n%s", diff)
	}
	ancestors := map[string][]string{
		"text/x-special": {"text/x-special", "text/plain"},
		"text/html":      {"text/html", "text/plain"},
	}
	db := new_app_database(dirs, func(m string) []string {
		if ans, found := ancestors[m]; found {
			return ans
		}
		return []string{m}
	})
	if len(db.Errors) != 1 || !strings.Contains(db.Errors[0].Error(), "broken.desktop") {
		t.Fatalf("Unexpected errors: %v", db.Errors)
	}
	ids := func(entries []*DesktopEntry) (ans []string) {
		for _, e := range entries {
			ans = append(ans, e.ID)
		}
		return
	}
	if diff := cmp.Diff([]string{"browser.desktop", "editor.desktop", "kde-okular.desktop", "viewer.desktop"}, ids(db.AllApps())); diff != "" {
		t.Fatalf("Incorrect list of all apps:\n%s", diff)
	}
	if e := db.AppByID("viewer"); e == nil || e.Name != "Viewer" {
		t.Fatalf("Higher priority desktop file did not override lower priority one: %#v", e)
	}
	if e := db.AppByID("hidden-from-menus.desktop"); e == nil {
		t.Fatalf("NoDisplay application not available")
	}
	// The desktop specific default refers first to an app that is not
	// installed and then to one that is
	if e := db.DefaultAppFor("image/png"); e == nil || e.ID != "editor.desktop" {
		t.Fatalf("Incorrect default for image/png: %#v", e)
	}
	for mime, expected := range map[string][]string{
		// editor.desktop is the default, even though its association is removed
		"image/png":                {"editor.desktop", "kde-okular.desktop", "viewer.desktop"},
		"application/pdf":          {"browser.desktop", "kde-okular.desktop"},
		"text/x-special":           {"editor.desktop", "hidden-from-menus.desktop", "browser.desktop"},
		"text/html":                {"editor.desktop", "browser.desktop"},
		"x-scheme-handler/https":   {"browser.desktop"},
		"application/x-kt-unknown": nil,
	} {
		if diff := cmp.Diff(expected, ids(db.AppsFor(mime))); diff != "" {
			t.Errorf("Incorrect apps for %s:\n%s", mime, diff)
		}
	}
	if m := MimeTypeForTarget(Target{URL: "HTTPS://x.com"}); m != "x-scheme-handler/https" {
		t.Fatalf("Incorrect MIME type for URL: %s", m)
	}
}
