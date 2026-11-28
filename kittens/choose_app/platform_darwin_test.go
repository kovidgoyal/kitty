// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

// use_bundle_ids makes application ids bundle ids for the duration of the
// test, as the other tests use desktop file ids on all platforms
func use_bundle_ids(t *testing.T) {
	old := app_id_suffix
	app_id_suffix = ""
	t.Cleanup(func() { app_id_suffix = old })
}

func make_bundle(t *testing.T, path, id, name, extra string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Join(path, "Contents"), 0o755); err != nil {
		t.Fatal(err)
	}
	info := fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>%s</string>
<key>CFBundleName</key><string>%s</string>
<key>CFBundleExecutable</key><string>%s-bin</string>
<key>CFBundlePackageType</key><string>APPL</string>
%s
</dict></plist>`, id, name, name, extra)
	if err := os.WriteFile(filepath.Join(path, "Contents", "Info.plist"), []byte(info), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestDarwinBundles(t *testing.T) {
	use_bundle_ids(t)
	if diff := cmp.Diff("Developer Tools", category_name("public.app-category.developer-tools")); diff != "" {
		t.Fatal(diff)
	}
	if category_name("something-else") != "" {
		t.Fatal("unexpected category name")
	}
	for _, x := range []any{true, "1", "YES", int64(1), uint64(2)} {
		if !plist_bool(x) {
			t.Fatalf("%#v is not true", x)
		}
	}
	for _, x := range []any{false, "0", "no", int64(0), nil} {
		if plist_bool(x) {
			t.Fatalf("%#v is not false", x)
		}
	}

	tdir := t.TempDir()
	apps := filepath.Join(tdir, "Applications")
	make_bundle(t, filepath.Join(apps, "Viewer.app"), "org.example.viewer", "Viewer",
		`<key>LSApplicationCategoryType</key><string>public.app-category.graphics-design</string>`)
	// an older copy in a sub-directory, which must not take precedence
	make_bundle(t, filepath.Join(apps, "Old", "Viewer.app"), "org.example.viewer", "Old Viewer", "")
	make_bundle(t, filepath.Join(apps, "Old", "Editor.app"), "org.example.editor", "Editor", "")
	make_bundle(t, filepath.Join(apps, "Agent.app"), "org.example.agent", "Agent", `<key>LSUIElement</key><string>1</string>`)
	make_bundle(t, filepath.Join(apps, "NotAnApp.app"), "org.example.framework", "Framework",
		`<key>CFBundlePackageType</key><string>FMWK</string>`)
	make_bundle(t, filepath.Join(tdir, "elsewhere", "Linked.app"), "org.example.linked", "Linked", "")
	if err := os.Symlink(filepath.Join(tdir, "elsewhere", "Linked.app"), filepath.Join(apps, "Linked.app")); err != nil {
		t.Fatal(err)
	}
	// symlinks to directories must not be followed, to avoid loops
	if err := os.Symlink(apps, filepath.Join(apps, "loop")); err != nil {
		t.Fatal(err)
	}
	db := &AppDatabase{dirs: &XDGDirs{}, by_id: map[string]*DesktopEntry{}}
	d := &darwin_apps{db: db, by_path: map[string]*DesktopEntry{}}
	d.scan(apps, 1)
	d.sort()
	type summary struct{ ID, Name, Path, Comment string }
	var actual []summary
	for _, e := range db.AllApps() {
		actual = append(actual, summary{e.ID, e.Name, e.Path, e.Comment})
	}
	expected := []summary{
		{"org.example.editor", "Editor", filepath.Join(apps, "Old", "Editor.app"), ""},
		{"org.example.linked", "Linked", filepath.Join(apps, "Linked.app"), ""},
		{"org.example.viewer", "Viewer", filepath.Join(apps, "Viewer.app"), "Graphics Design"},
	}
	if diff := cmp.Diff(expected, actual); diff != "" {
		t.Fatalf("unexpected apps:\n%s", diff)
	}
	if e := db.AppByID("org.example.agent"); e == nil || e.ShouldShow(nil) {
		t.Fatalf("background applications must be usable but not shown: %#v", e)
	}
	if db.AppByID("org.example.framework") != nil {
		t.Fatal("non-applications must be ignored")
	}
	// finding the bundle via its real path, as LaunchServices does
	real_path, _ := filepath.EvalSymlinks(filepath.Join(tdir, "elsewhere", "Linked.app"))
	if e := d.add(real_path, false); e == nil || e.ID != "org.example.linked" {
		t.Fatalf("symlinked bundle not found via its real path: %#v", e)
	}
	viewer := db.AppByID("org.example.viewer")
	if diff := cmp.Diff([]string{"Viewer-bin"}, viewer.Keywords); diff != "" {
		t.Fatalf("unexpected keywords:\n%s", diff)
	}
	cmds, err := viewer.Commands(Target{Path: "/a b.png"}, Target{URL: "https://x.com"})
	if err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([][]string{{"/usr/bin/open", "-a", viewer.Path, "/a b.png", "https://x.com"}}, cmds); diff != "" {
		t.Fatalf("unexpected commands:\n%s", diff)
	}
}

func TestDarwinLaunchServices(t *testing.T) {
	use_bundle_ids(t)
	tdir := t.TempDir()
	for _, x := range []string{"a.pdf", "b.png"} {
		if err := os.WriteFile(filepath.Join(tdir, x), nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Mkdir(filepath.Join(tdir, "doc.rtfd"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(tdir, "a.pdf"), filepath.Join(tdir, "link")); err != nil {
		t.Fatal(err)
	}
	for name, expected := range map[string]string{
		"a.pdf": "application/pdf", "b.png": "image/png", "link": "application/pdf", "doc.rtfd": "x-apple-uti/com.apple.rtfd",
		".": "inode/directory", "missing.pdf": "application/pdf",
	} {
		if actual := MimeTypeForTarget(Target{Path: filepath.Join(tdir, name)}); actual != expected {
			t.Fatalf("unexpected MIME type for %s: %s != %s", name, expected, actual)
		}
	}
	db := LoadAppDatabase()
	if e := db.DefaultAppFor("inode/directory"); e == nil || e.ID != "com.apple.finder" {
		t.Fatalf("Finder is not the default application for folders: %#v", e)
	}
	if e := db.AppByID("com.apple.finder"); e == nil || !e.ShouldShow(nil) {
		t.Fatalf("Finder is not shown: %#v", e)
	}
}
