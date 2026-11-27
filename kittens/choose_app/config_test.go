// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestOpenWithRules(t *testing.T) {
	for _, spec := range []string{
		"", "mime:image/*", "image/* imv", "size:10 imv", "mime: imv", "ext:, imv",
		"mime:[ imv", "glob:/a/[ x", "ext:pdf desktop:", "ext:pdf desktop:okular extra", `ext:pdf "unterminated`,
	} {
		if _, err := ParseOpenWith(spec); err == nil {
			t.Errorf("Parsing the invalid open_with %#v did not fail", spec)
		}
	}
	if diff := cmp.Diff([]string{"gz", "tar.gz"}, extensions_of("A.TAR.GZ")); diff != "" {
		t.Fatalf("Incorrect extensions:\n%s", diff)
	}
	if diff := cmp.Diff([]string{"txt"}, extensions_of(".hidden.txt")); diff != "" {
		t.Fatalf("Incorrect extensions for hidden file:\n%s", diff)
	}
	if x := extensions_of(".bashrc"); len(x) != 0 {
		t.Fatalf("Hidden file without extension has extensions: %#v", x)
	}
	if x := extensions_of("trailing."); len(x) != 0 {
		t.Fatalf("File with trailing dot has extensions: %#v", x)
	}

	home, err := os.UserHomeDir()
	if err != nil {
		t.Fatal(err)
	}
	png := Target{Path: "/x/Photo.PNG"}
	tgz := Target{Path: "/x/a.tar.gz"}
	note := Target{Path: filepath.Join(home, "notes", "sub", "a.md")}
	https := Target{URL: "https://example.com/a.pdf"}
	png_mimes := []string{"image/png"}
	py_mimes := []string{"text/x-python", "text/plain"}
	url_mimes := []string{"x-scheme-handler/https"}
	type tc struct {
		target Target
		mimes  []string
		match  bool
	}
	for spec, cases := range map[string][]tc{
		"mime:image/* imv": {{png, png_mimes, true}, {tgz, py_mimes, false}, {https, url_mimes, false}},
		// sub-classes match
		"mime:text/plain,application/pdf x": {{png, py_mimes, true}, {png, png_mimes, false}},
		"mime:X-Scheme-Handler/* x":         {{https, url_mimes, true}},
		"ext:png,.jpg x":                    {{png, nil, true}, {tgz, nil, false}, {https, nil, false}},
		"ext:tar.* x":                       {{tgz, nil, true}, {png, nil, false}},
		"ext:gz x":                          {{tgz, nil, true}},
		"glob:Photo.* x":                    {{png, nil, true}, {tgz, nil, false}},
		"glob:photo.* x":                    {{png, nil, false}},
		"glob:~/notes/** x":                 {{note, nil, true}, {png, nil, false}, {https, nil, false}},
		"glob:/x/*.png x":                   {{png, nil, false}},
		"glob:/x/*.PNG x":                   {{png, nil, true}},
		"scheme:http,HTTPS x":               {{https, nil, true}, {png, nil, false}},
		"scheme:file x":                     {{png, nil, true}, {https, nil, false}},
	} {
		rule, err := ParseOpenWith(spec)
		if err != nil {
			t.Fatalf("Failed to parse %#v with error: %s", spec, err)
		}
		for _, c := range cases {
			if rule.Matches(c.target, c.mimes) != c.match {
				t.Errorf("open_with %#v matching %s with MIME types %v is not %v", spec, c.target, c.mimes, c.match)
			}
		}
	}

	rule, err := ParseOpenWith("ext:pdf desktop:org.kde.okular")
	if err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff(Choice{DesktopID: "org.kde.okular.desktop"}, rule.Choice); diff != "" {
		t.Fatalf("Incorrect desktop choice:\n%s", diff)
	}
	rule, err = ParseOpenWith(`ext:pdf 'my viewer' --title "%c" %F`)
	if err != nil {
		t.Fatal(err)
	}
	e, err := rule.Choice.Entry(nil)
	if err != nil {
		t.Fatal(err)
	}
	cmds, err := e.Commands(png, tgz)
	if err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([][]string{{"my viewer", "--title", e.Name, png.Path, tgz.Path}}, cmds); diff != "" {
		t.Fatalf("Incorrect commands for custom command:\n%s", diff)
	}
	if e.Name != `'my viewer' --title %c %F` {
		t.Fatalf("Incorrect name for custom command: %#v", e.Name)
	}
	rule, err = ParseOpenWith(`ext:pdf viewer`)
	if err != nil {
		t.Fatal(err)
	}
	e, err = rule.Choice.Entry(nil)
	if err != nil {
		t.Fatal(err)
	}
	if cmds, err = e.Commands(png, tgz); err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([][]string{{"viewer", png.Path}, {"viewer", tgz.Path}}, cmds); diff != "" {
		t.Fatalf("Incorrect commands for custom command without field codes:\n%s", diff)
	}
	if again, err := e.Commands(png); err != nil || len(again) != 1 || len(again[0]) != 2 {
		t.Fatalf("Expanding commands modified the custom command: %#v %v", again, err)
	}
}

func TestChoiceStore(t *testing.T) {
	tdir := t.TempDir()
	path := filepath.Join(tdir, "sub", "choices.json")
	s, err := LoadChoiceStore(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, found := s.Remembered("image/png"); found {
		t.Fatalf("Empty store has remembered choices")
	}
	viewer, editor := ChoiceForDesktopID("viewer"), Choice{Cmdline: []string{"editor", "%f"}}
	if err = s.RecordChoice("image/png", viewer, false); err != nil {
		t.Fatal(err)
	}
	if _, found := s.Remembered("image/png"); found {
		t.Fatalf("Choice remembered when not requested")
	}
	if err = s.RecordChoice("image/png", editor, true); err != nil {
		t.Fatal(err)
	}
	if err = s.RecordChoice("image/png", viewer, false); err != nil {
		t.Fatal(err)
	}
	s2, err := LoadChoiceStore(path)
	if err != nil {
		t.Fatal(err)
	}
	if c, found := s2.Remembered("image/png"); !found || !c.Equal(editor) {
		t.Fatalf("Incorrect remembered choice: %#v", c)
	}
	if diff := cmp.Diff([]Choice{viewer, editor}, s2.Recent("image/png")); diff != "" {
		t.Fatalf("Incorrect recent choices:\n%s", diff)
	}
	for i := range max_recent_choices + 3 {
		if err = s.RecordChoice("text/plain", Choice{Cmdline: []string{fmt.Sprint(i)}}, false); err != nil {
			t.Fatal(err)
		}
	}
	if r := s.Recent("text/plain"); len(r) != max_recent_choices || r[0].Cmdline[0] != fmt.Sprint(max_recent_choices+2) {
		t.Fatalf("Recent choices not capped correctly: %#v", r)
	}
	forgotten, err := s.Forget("image/png", "text/plain")
	if err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]string{"image/png"}, forgotten); diff != "" {
		t.Fatalf("Incorrect forgotten MIME types:\n%s", diff)
	}
	if _, found := s.Remembered("image/png"); found {
		t.Fatalf("Choice not forgotten")
	}
	if len(s.Recent("image/png")) != 2 {
		t.Fatalf("Forgetting removed recent choices")
	}

	// Concurrent writers do not lose each others changes
	var wg sync.WaitGroup
	for i := range 10 {
		wg.Go(func() {
			ws, _ := LoadChoiceStore(path)
			if err := ws.RecordChoice(fmt.Sprintf("x-test/%d", i), viewer, true); err != nil {
				t.Error(err)
			}
		})
	}
	wg.Wait()
	s, err = LoadChoiceStore(path)
	if err != nil {
		t.Fatal(err)
	}
	for i := range 10 {
		if _, found := s.Remembered(fmt.Sprintf("x-test/%d", i)); !found {
			t.Fatalf("Concurrent write %d was lost", i)
		}
	}

	// A corrupted file is reported and then replaced
	if err = os.WriteFile(path, []byte("{garbage"), 0o600); err != nil {
		t.Fatal(err)
	}
	if s, err = LoadChoiceStore(path); err == nil || !strings.Contains(err.Error(), "corrupted") {
		t.Fatalf("Corrupted file not reported: %v", err)
	}
	if err = s.RecordChoice("image/png", viewer, true); err != nil {
		t.Fatalf("Corrupted file not replaced: %s", err)
	}
	if _, err = LoadChoiceStore(path); err != nil {
		t.Fatal(err)
	}
	// A file from a different version is not overwritten
	if err = os.WriteFile(path, []byte(`{"version": 1000}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if s, err = LoadChoiceStore(path); err == nil {
		t.Fatalf("Unknown version not reported")
	}
	if err = s.RecordChoice("image/png", viewer, true); err == nil {
		t.Fatalf("File with unknown version was overwritten")
	}
}

func TestResolver(t *testing.T) {
	tdir := t.TempDir()
	w := func(path, text string) { write_test_file(t, filepath.Join(tdir, path), text) }
	app := func(name, mime string) string {
		return "[Desktop Entry]\nType=Application\nName=" + name + "\nExec=" + name + " %f\nMimeType=" + mime + ";\n"
	}
	w("sys/applications/viewer.desktop", app("viewer", "image/png"))
	w("sys/applications/browser.desktop", app("browser", "x-scheme-handler/https"))
	w("config/mimeapps.list", "[Default Applications]\nimage/png=viewer.desktop\nx-scheme-handler/https=browser.desktop\n")
	db := new_app_database(&XDGDirs{
		DataHome: filepath.Join(tdir, "home"), ConfigHome: filepath.Join(tdir, "config"),
		DataDirs: []string{filepath.Join(tdir, "sys")},
	}, func(m string) []string { return []string{m} })
	store, err := LoadChoiceStore(filepath.Join(tdir, "choices.json"))
	if err != nil {
		t.Fatal(err)
	}
	cfg := NewConfig()
	cfg.Open_with = []string{"ext:png desktop:not-installed", "scheme:https firefox --new-tab %u"}
	settings, err := settings_from_config(cfg)
	if err != nil {
		t.Fatal(err)
	}
	r := &Resolver{Settings: settings, Store: store, DB: db}
	png, https := Target{Path: filepath.Join(tdir, "a.png")}, Target{URL: "https://example.com"}
	txt := Target{Path: filepath.Join(tdir, "a.kitty-test-unknown-ext")}

	res, found, warnings := r.Resolve(https)
	if !found || res.Source != "open_with" || res.Choice.Cmdline[0] != "firefox" || len(warnings) != 0 {
		t.Fatalf("Incorrect resolution for URL: %#v %v %v", res, found, warnings)
	}
	res, found, warnings = r.Resolve(png)
	if !found || res.Source != "system_default" || res.Choice.DesktopID != "viewer.desktop" || len(warnings) != 1 || !strings.Contains(warnings[0], "ignoring open_with") {
		t.Fatalf("Incorrect resolution for PNG: %#v %v %v", res, found, warnings)
	}
	if err = store.RecordChoice("image/png", Choice{Cmdline: []string{"gimp"}}, true); err != nil {
		t.Fatal(err)
	}
	res, found, _ = r.Resolve(png)
	if !found || res.Source != "remembered" || res.Choice.Cmdline[0] != "gimp" {
		t.Fatalf("Remembered choice not used: %#v %v", res, found)
	}
	if err = store.RecordChoice("image/png", ChoiceForDesktopID("uninstalled"), true); err != nil {
		t.Fatal(err)
	}
	res, found, warnings = r.Resolve(png)
	if !found || res.Source != "system_default" || len(warnings) != 2 || !strings.Contains(warnings[1], "remembered") {
		t.Fatalf("Uninstalled remembered choice not skipped: %#v %v %v", res, found, warnings)
	}
	settings.Use_system_defaults = false
	if res, found, _ = r.Resolve(png); found {
		t.Fatalf("System default used when disabled: %#v", res)
	}
	if res, found, _ = r.Resolve(txt); found {
		t.Fatalf("Unknown file type resolved: %#v", res)
	}
}
