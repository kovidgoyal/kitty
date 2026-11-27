// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/utils"
)

type launched struct {
	Argv []string
	Cwd  string
}

func TestOpenTargets(t *testing.T) {
	tdir := t.TempDir()
	w := func(path, text string) string {
		write_test_file(t, filepath.Join(tdir, path), text)
		return filepath.Join(tdir, path)
	}
	w("sys/applications/viewer.desktop", "[Desktop Entry]\nType=Application\nName=Viewer\nExec=viewer %f\nPath=/viewer/dir\nMimeType=application/pdf;\n")
	w("sys/applications/editor.desktop", "[Desktop Entry]\nType=Application\nName=Editor\nExec=editor %F\nTerminal=true\n")
	w("config/mimeapps.list", "[Default Applications]\napplication/pdf=viewer.desktop\n")
	db := new_app_database(&XDGDirs{
		DataHome: filepath.Join(tdir, "home"), ConfigHome: filepath.Join(tdir, "config"),
		DataDirs: []string{filepath.Join(tdir, "sys")},
	}, func(m string) []string { return []string{m} })
	store, err := LoadChoiceStore(filepath.Join(tdir, "choices.json"))
	if err != nil {
		t.Fatal(err)
	}
	cfg := NewConfig()
	cfg.Open_with = []string{"ext:png imv %F", "ext:md terminal:nvim"}
	settings, err := settings_from_config(cfg)
	if err != nil {
		t.Fatal(err)
	}
	r := &Resolver{Settings: settings, Store: store, DB: db}
	a_pdf, b_pdf := w("files/a.pdf", ""), w("files/b.pdf", "")
	a_png, b_png := w("files/a.png", ""), w("files/b.png", "")
	a_md := w("files/a.md", "")
	a_txt, b_txt := w("files/a.kt-unknown-ext", ""), w("files/b.kt-unknown-ext", "")
	targets := func(paths ...string) (ans []Target) {
		for _, p := range paths {
			ans = append(ans, Target{Path: p})
		}
		return
	}
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	kitty := utils.KittyExe()

	var runs []launched
	run := func(argv []string, cwd string) error {
		runs = append(runs, launched{argv, cwd})
		return nil
	}
	var asked [][]Target
	answer := &Result{Choice: ChoiceForDesktopID("editor")}
	ask := func(t []Target) (*Result, error) {
		asked = append(asked, t)
		return answer, nil
	}
	reset := func() { runs, asked = nil, nil }

	// Files are grouped by application, single file applications are run
	// once per file and terminal programs run in kitty
	if err = open_targets(r, targets(a_pdf, a_png, b_pdf, b_png, a_md), false, ask, run); err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]launched{
		{[]string{"viewer", a_pdf}, "/viewer/dir"}, {[]string{"viewer", b_pdf}, "/viewer/dir"},
		{[]string{"imv", a_png, b_png}, cwd},
		{[]string{kitty, "--", "nvim", a_md}, cwd},
	}, runs); diff != "" {
		t.Fatalf("Incorrect launches:\n%s", diff)
	}
	if len(asked) != 0 {
		t.Fatalf("Asked when all files were known: %v", asked)
	}

	// Unknown files are asked about once per MIME type
	reset()
	if err = open_targets(r, targets(a_txt, a_pdf, b_txt), false, ask, run); err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([][]Target{targets(a_txt, b_txt)}, asked); diff != "" {
		t.Fatalf("Incorrect questions:\n%s", diff)
	}
	if diff := cmp.Diff([]launched{
		{[]string{"viewer", a_pdf}, "/viewer/dir"},
		{[]string{kitty, "--", "editor", a_txt, b_txt}, cwd},
	}, runs); diff != "" {
		t.Fatalf("Incorrect launches after asking:\n%s", diff)
	}

	// Always asking
	reset()
	if err = open_targets(r, targets(a_pdf), true, ask, run); err != nil {
		t.Fatal(err)
	}
	if len(asked) != 1 || len(runs) != 1 || runs[0].Argv[2] != "editor" {
		t.Fatalf("Did not ask when always asking: %v %v", asked, runs)
	}

	// A custom terminal
	reset()
	settings.Terminal = "foot -e"
	if err = open_targets(r, targets(a_md), false, ask, run); err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]string{"foot", "-e", "nvim", a_md}, runs[0].Argv); diff != "" {
		t.Fatalf("Incorrect command with custom terminal:\n%s", diff)
	}
	settings.Terminal = "kitty"

	// Failures, with exit codes like xdg-open
	exit_code := func(err error) int {
		var oe *open_error
		if errors.As(err, &oe) {
			return oe.exit_code
		}
		return -1
	}
	reset()
	err = open_targets(r, targets(a_pdf, filepath.Join(tdir, "missing.pdf")), false, ask, run)
	if exit_code(err) != exit_missing_file || !strings.Contains(err.Error(), "missing.pdf") || len(runs) != 0 {
		t.Fatalf("Missing file not reported correctly: %v %v", err, runs)
	}
	reset()
	answer = nil
	err = open_targets(r, targets(a_txt, a_pdf), false, ask, run)
	if exit_code(err) != exit_no_app || len(runs) != 1 {
		t.Fatalf("Cancelling not reported correctly, or known files not opened: %v %v", err, runs)
	}
	reset()
	err = open_targets(r, targets(a_pdf), false, ask, func([]string, string) error { return errors.New("boom") })
	if exit_code(err) != exit_launch_error || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("Launch failure not reported correctly: %v", err)
	}
	reset()
	err = open_targets(r, targets(a_txt), false, func([]Target) (*Result, error) { return nil, errors.New("no panel") }, run)
	if exit_code(err) != exit_no_app || !strings.Contains(err.Error(), "no panel") {
		t.Fatalf("Ask failure not reported correctly: %v", err)
	}
	// URLs are not checked for existence
	reset()
	answer = &Result{Choice: Choice{Cmdline: []string{"browser", "%u"}}}
	if err = open_targets(r, []Target{{URL: "https://example.com"}}, false, ask, run); err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]string{"browser", "https://example.com"}, runs[0].Argv); diff != "" {
		t.Fatalf("Incorrect command for URL:\n%s", diff)
	}
}

func TestLaunchDetached(t *testing.T) {
	tdir := t.TempDir()
	out := filepath.Join(tdir, "out")
	if err := launch_detached([]string{"sh", "-c", "pwd > out.tmp; mv out.tmp out"}, tdir); err != nil {
		t.Fatal(err)
	}
	if err := launch_detached([]string{filepath.Join(tdir, "nonexistent-program")}, tdir); err == nil {
		t.Fatalf("Launching a non-existent program did not fail")
	}
	for range 500 {
		if data, err := os.ReadFile(out); err == nil {
			if strings.TrimSpace(string(data)) != tdir {
				t.Fatalf("Program not run in the correct directory: %s", data)
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("Detached program did not run")
}
