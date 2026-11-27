// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/fzf"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
)

func TestChooserItems(t *testing.T) {
	tdir := t.TempDir()
	w := func(path, text string) { write_test_file(t, filepath.Join(tdir, path), text) }
	app := func(name, exec, extra string) string {
		return "[Desktop Entry]\nType=Application\nName=" + name + "\nExec=" + exec + "\n" + extra
	}
	w("sys/applications/okular.desktop", app("Okular", "okular %U", "MimeType=application/pdf;\n"))
	w("sys/applications/okular-pdf.desktop", app("Okular", "okular %U", "NoDisplay=true\nMimeType=application/pdf;\n"))
	w("sys/applications/zathura.desktop", app("Zathura", "zathura %f", "MimeType=application/pdf;image/png;\n"))
	w("sys/applications/viewer.desktop", app("Image Viewer", "imv %F", "MimeType=image/png;\nGenericName=Pictures\nKeywords=photo;gallery;\n"))
	w("sys/applications/editor.desktop", app("Editor", "kate %U", "Keywords=text;code;\n"))
	w("sys/applications/hidden.desktop", app("Hidden", "hidden %U", "NoDisplay=true\n"))
	w("config/mimeapps.list", "[Default Applications]\napplication/pdf=zathura.desktop\n")
	db := new_app_database(&XDGDirs{
		DataHome: filepath.Join(tdir, "home"), ConfigHome: filepath.Join(tdir, "config"),
		DataDirs: []string{filepath.Join(tdir, "sys")},
	}, func(m string) []string { return []string{m} })
	store, err := LoadChoiceStore(filepath.Join(tdir, "choices.json"))
	if err != nil {
		t.Fatal(err)
	}
	pdf, png := Target{Path: filepath.Join(tdir, "a.pdf")}, Target{Path: filepath.Join(tdir, "a.png")}
	type summary struct {
		ID          string
		Recommended bool
	}
	summarize := func(items []*item) (ans []summary) {
		for _, it := range items {
			ans = append(ans, summary{it.choice.String(), it.recommended})
		}
		return
	}
	// The default first, the duplicate Okular entry removed and the hidden
	// application not shown
	expected := []summary{
		{"desktop:zathura.desktop", true}, {"desktop:okular-pdf.desktop", true},
		{"desktop:editor.desktop", false}, {"desktop:viewer.desktop", false},
	}
	if diff := cmp.Diff(expected, summarize(build_items(db, store, []Target{pdf}))); diff != "" {
		t.Fatalf("Incorrect items for PDF:\n%s", diff)
	}
	// Recently chosen applications come first, including custom commands
	custom := Choice{Cmdline: []string{"mupdf"}}
	if err = store.RecordChoice("application/pdf", custom, false); err != nil {
		t.Fatal(err)
	}
	if err = store.RecordChoice("application/pdf", ChoiceForDesktopID("editor"), false); err != nil {
		t.Fatal(err)
	}
	expected = []summary{
		{"desktop:editor.desktop", true}, {"mupdf", true}, {"desktop:zathura.desktop", true}, {"desktop:okular-pdf.desktop", true},
		{"desktop:viewer.desktop", false},
	}
	if diff := cmp.Diff(expected, summarize(build_items(db, store, []Target{pdf}))); diff != "" {
		t.Fatalf("Incorrect items for PDF with recent choices:\n%s", diff)
	}
	// Multiple types recommend only the applications that can open all of them
	both := summarize(build_items(db, store, []Target{png, pdf}))
	if diff := cmp.Diff(summary{"desktop:zathura.desktop", true}, both[0]); diff != "" || both[1].Recommended {
		t.Fatalf("Incorrect items for multiple types: %#v", both)
	}
	// With no targets there are no recommendations
	for _, s := range summarize(build_items(db, store, nil)) {
		if s.Recommended {
			t.Fatalf("Recommended item with no targets: %#v", s)
		}
	}

	items := build_items(db, store, []Target{pdf})
	m := fzf.NewFuzzyMatcher(fzf.DEFAULT_SCHEME)
	for query, expected := range map[string][]string{
		"":     {"desktop:editor.desktop", "mupdf", "desktop:zathura.desktop", "desktop:okular-pdf.desktop", "desktop:viewer.desktop"},
		"zat":  {"desktop:zathura.desktop"},
		"ok":   {"desktop:okular-pdf.desktop"},
		"imv":  {"desktop:viewer.desktop"},
		"gall": {"desktop:viewer.desktop"},
		// letters scattered across keywords do not match
		"phgl": nil,
		"e":    {"desktop:editor.desktop", "desktop:viewer.desktop"},
	} {
		matches, err := filter_items(items, query, m)
		if err != nil {
			t.Fatal(err)
		}
		var actual []string
		for _, it := range matches {
			actual = append(actual, it.choice.String())
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Errorf("Incorrect matches for %#v:\n%s", query, diff)
		}
	}
	matches, err := filter_items(items, "zat", m)
	if err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff([]int{0, 1, 2}, matches[0].name_positions); diff != "" {
		t.Fatalf("Incorrect match positions:\n%s", diff)
	}
}

func TestChooserGrid(t *testing.T) {
	items := make([]*item, 7)
	for i := range items {
		items[i] = &item{recommended: i < 2}
	}
	rows := layout_grid(items, true, 3)
	type r struct {
		H string
		I []int
	}
	var actual []r
	for _, x := range rows {
		actual = append(actual, r{x.header, x.items})
	}
	if diff := cmp.Diff([]r{{"Recommended", nil}, {"", []int{0, 1}}, {"Other applications", nil}, {"", []int{2, 3, 4}}, {"", []int{5, 6}}}, actual); diff != "" {
		t.Fatalf("Incorrect layout:\n%s", diff)
	}
	if n := len(layout_grid(items, false, 3)); n != 3 {
		t.Fatalf("Incorrect number of rows without sections: %d", n)
	}
	if rows := layout_grid(items[2:], true, 3); rows[0].header != "All applications" {
		t.Fatalf("Incorrect header with no recommendations: %#v", rows[0])
	}
	for _, tc := range []struct{ idx, amt, expected int }{
		{0, 1, 2}, {1, 1, 3}, {2, -1, 0}, {4, -1, 1}, {4, 1, 6}, {3, 1, 6}, {2, 1, 5},
		{0, 10, 5}, {6, -10, 1}, {0, -1, 0}, {6, 1, 6},
	} {
		if actual := move_vertically(rows, tc.idx, tc.amt); actual != tc.expected {
			t.Errorf("Moving %d from %d gave %d instead of %d", tc.amt, tc.idx, actual, tc.expected)
		}
	}
	if num_grid_columns(5) != 1 || num_grid_columns(tile_width*3+1) != 3 {
		t.Fatalf("Incorrect number of grid columns")
	}
}

func TestWrapName(t *testing.T) {
	type wl = wrapped_line
	for _, tc := range []struct {
		text     string
		width    int
		expected []wrapped_line
	}{
		{"Short", 10, []wl{{0, 5, false}}},
		{"LibreOffice Writer", 14, []wl{{0, 11, false}, {12, 18, false}}},
		{"GNU Image Manipulation Program", 14, []wl{{0, 9, false}, {10, 23, true}}},
		{"Averyveryverylongname", 10, []wl{{0, 10, false}, {10, 19, true}}},
		{"  spaced  ", 10, []wl{{2, 10, false}}},
		{"", 10, nil},
	} {
		if diff := cmp.Diff(tc.expected, wrap_name(tc.text, tc.width, 2), cmp.AllowUnexported(wrapped_line{})); diff != "" {
			t.Errorf("Incorrect wrapping of %#v:\n%s", tc.text, diff)
		}
	}
}

func TestTerminalChoices(t *testing.T) {
	for spec, expected := range map[string]Choice{
		"ext:md terminal:nvim %F":  {Cmdline: []string{"nvim", "%F"}, Terminal: true},
		"ext:md terminal: nvim -R": {Cmdline: []string{"nvim", "-R"}, Terminal: true},
		"ext:md nvim":              {Cmdline: []string{"nvim"}},
	} {
		rule, err := ParseOpenWith(spec)
		if err != nil {
			t.Fatalf("Failed to parse %#v with error: %s", spec, err)
		}
		if diff := cmp.Diff(expected, rule.Choice); diff != "" {
			t.Fatalf("Incorrect choice for %#v:\n%s", spec, diff)
		}
	}
	for _, spec := range []string{"ext:md terminal:", "ext:md terminal: ''"} {
		if _, err := ParseOpenWith(spec); err == nil {
			t.Errorf("Parsing %#v did not fail", spec)
		}
	}
	c := Choice{Cmdline: []string{"nvim", "my file"}, Terminal: true}
	if s := c.String(); s != "terminal:nvim 'my file'" {
		t.Fatalf("Incorrect string for terminal choice: %#v", s)
	}
	if c.Equal(Choice{Cmdline: c.Cmdline}) {
		t.Fatalf("Terminal not considered in equality")
	}
	e, err := c.Entry(nil)
	if err != nil || !e.Terminal {
		t.Fatalf("Entry for terminal choice not marked as terminal: %#v %v", e, err)
	}
}

func TestCommandCompleter(t *testing.T) {
	tdir := t.TempDir()
	bin := filepath.Join(tdir, "bin")
	write_test_file(t, filepath.Join(bin, "kt-test-viewer"), "")
	if err := os.Chmod(filepath.Join(bin, "kt-test-viewer"), 0o755); err != nil {
		t.Fatal(err)
	}
	write_test_file(t, filepath.Join(bin, "kt-test-notexec"), "")
	write_test_file(t, filepath.Join(tdir, "docs", "kt-a.md"), "")
	t.Setenv("PATH", bin)
	complete := command_completer(func() *readline.Readline { return nil })
	words := func(before string) (ans []string) {
		c := complete(before, "")
		for _, g := range c.Groups {
			for _, m := range g.Matches {
				ans = append(ans, g.Title+":"+m.Word)
			}
		}
		return
	}
	if diff := cmp.Diff([]string{"Executables in PATH:kt-test-viewer"}, words("kt-test")); diff != "" {
		t.Fatalf("Incorrect executable completions:\n%s", diff)
	}
	if diff := cmp.Diff([]string{"Executables in PATH:kt-test-viewer"}, words("terminal:kt-test")); diff != "" {
		t.Fatalf("Incorrect executable completions with terminal prefix:\n%s", diff)
	}
	if diff := cmp.Diff([]string{"Field codes:%f", "Field codes:%F"}, words("kt-test-viewer %")[:2]); diff != "" {
		t.Fatalf("Incorrect field code completions:\n%s", diff)
	}
	if diff := cmp.Diff([]string{"Field codes:%U"}, words("x %U")); diff != "" {
		t.Fatalf("Incorrect field code completions:\n%s", diff)
	}
	if diff := cmp.Diff([]string{"Files:" + filepath.Join(tdir, "docs", "kt-a.md")}, words("x "+filepath.Join(tdir, "docs", "kt-"))); diff != "" {
		t.Fatalf("Incorrect file completions:\n%s", diff)
	}
	if c := complete("x --flag ab", ""); c.CurrentWordIdx != len("x --flag ") {
		t.Fatalf("Incorrect current word index: %d", c.CurrentWordIdx)
	}
}
