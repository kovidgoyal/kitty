// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/fzf"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
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
	if diff := cmp.Diff(expected, summarize(build_items(db, store, NewChooserInput([]Target{pdf})))); diff != "" {
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
	if diff := cmp.Diff(expected, summarize(build_items(db, store, NewChooserInput([]Target{pdf})))); diff != "" {
		t.Fatalf("Incorrect items for PDF with recent choices:\n%s", diff)
	}
	// Multiple types recommend only the applications that can open all of them
	both := summarize(build_items(db, store, NewChooserInput([]Target{png, pdf})))
	if diff := cmp.Diff(summary{"desktop:zathura.desktop", true}, both[0]); diff != "" || both[1].Recommended {
		t.Fatalf("Incorrect items for multiple types: %#v", both)
	}
	// With no targets there are no recommendations
	for _, s := range summarize(build_items(db, store, NewChooserInput(nil))) {
		if s.Recommended {
			t.Fatalf("Recommended item with no targets: %#v", s)
		}
	}

	// Explicitly recommended applications come after the recent ones and the
	// MIME type can be specified without files
	input := &ChooserInput{MimeTypes: []string{"application/pdf"}, Recommend: []Choice{ChoiceForDesktopID("viewer"), ChoiceForDesktopID("not-installed")}}
	expected = []summary{
		{"desktop:editor.desktop", true}, {"mupdf", true}, {"desktop:viewer.desktop", true},
		{"desktop:zathura.desktop", true}, {"desktop:okular-pdf.desktop", true},
	}
	if diff := cmp.Diff(expected, summarize(build_items(db, store, input))); diff != "" {
		t.Fatalf("Incorrect items with explicit recommendations:\n%s", diff)
	}

	items := build_items(db, store, NewChooserInput([]Target{pdf}))
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
	rows := layout_grid(items, true, 3, default_tile_geometry)
	type r struct {
		H string
		I []int
	}
	var actual []r
	for _, x := range rows {
		actual = append(actual, r{x.header, x.items})
		if x.height() != utils.IfElse(x.is_header(), 1, default_tile_geometry.height()) {
			t.Fatalf("Incorrect row height: %d", x.height())
		}
	}
	if diff := cmp.Diff([]r{{"Recommended", nil}, {"", []int{0, 1}}, {"Other applications", nil}, {"", []int{2, 3, 4}}, {"", []int{5, 6}}}, actual); diff != "" {
		t.Fatalf("Incorrect layout:\n%s", diff)
	}
	if n := len(layout_grid(items, false, 3, default_tile_geometry)); n != 3 {
		t.Fatalf("Incorrect number of rows without sections: %d", n)
	}
	if rows := layout_grid(items[2:], true, 3, default_tile_geometry); rows[0].header != "All applications" {
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
	if num_grid_columns(5, default_tile_geometry) != 1 || num_grid_columns(default_tile_geometry.width()*3+1, default_tile_geometry) != 3 {
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

func TestGridScroll(t *testing.T) {
	// A header and 4 rows of tiles, of total height 1 + 4*7 = 29
	rows := []grid_row{{header: "H"}, {items: []int{0}, tile_height: 7}, {items: []int{1}, tile_height: 7}, {items: []int{2}, tile_height: 7}, {items: []int{3}, tile_height: 7}}
	g := new_grid_scroll(rows)
	if diff := cmp.Diff([]int{0, 1, 8, 15, 22}, g.offsets); diff != "" || g.total != 29 {
		t.Fatalf("Incorrect offsets: %d\n%s", g.total, diff)
	}
	for line, expected := range map[int][2]int{-1: {-1, 0}, 0: {0, 0}, 1: {1, 0}, 7: {1, 6}, 8: {2, 0}, 28: {4, 6}, 29: {-1, 0}} {
		if r, k := g.row_at(line); r != expected[0] || k != expected[1] {
			t.Fatalf("Incorrect row for line %d: (%d, %d) != %v", line, r, k, expected)
		}
	}
	if r, _ := new_grid_scroll(nil).row_at(0); r != -1 {
		t.Fatalf("Empty grid has a row")
	}
	// Scrolling a row into view
	for _, tc := range []struct{ top, bottom, pos, viewport, expected int }{
		{10, 17, 5, 15, -1},
		{10, 17, 12, 15, 10},
		{10, 17, 0, 15, 2},
		// Rows taller than the viewport show their top
		{10, 30, 0, 15, 10},
	} {
		if got := target_for_row(tc.top, tc.bottom, tc.pos, tc.viewport); got != tc.expected {
			t.Fatalf("Incorrect scroll target for %v: %d", tc, got)
		}
	}
}

func TestTileSize(t *testing.T) {
	for _, tc := range []struct {
		icon_size, tile_width string
		ok                    bool
	}{{"3", "16", true}, {"1", "8", true}, {"7", "64", true}, {"8", "16", false}, {"3", "7", false}, {"3", "65", false}} {
		cfg := NewConfig()
		if err := cfg.Parse("icon_size", tc.icon_size); err != nil {
			t.Fatal(err)
		}
		if err := cfg.Parse("tile_width", tc.tile_width); err != nil {
			t.Fatal(err)
		}
		s, err := settings_from_config(cfg)
		if (err == nil) != tc.ok {
			t.Fatalf("Validity of icon_size %s and tile_width %s not detected: %v", tc.icon_size, tc.tile_width, err)
		}
		if err == nil && (s.tiles.width() != int(cfg.Tile_width) || s.tiles.icon_rows != int(cfg.Icon_size) || s.tiles.height() != int(cfg.Icon_size)+4) {
			t.Fatalf("Incorrect tile geometry: %#v", s.tiles)
		}
	}
	if default_tile_geometry != (tile_geometry{icon_rows: 3, name_lines: 2, content_width: 14}) {
		t.Fatalf("Default tile geometry changed: %#v", default_tile_geometry)
	}
	cfg := NewConfig()
	if s, err := settings_from_config(cfg); err != nil || s.tiles != default_tile_geometry {
		t.Fatalf("Default settings do not give the default tile geometry: %#v %v", s, err)
	}
}

func TestActivationTokenIds(t *testing.T) {
	a, b := activation_token_id("token"), activation_token_id("token")
	if a == b || !loop.IsValidActivationTokenId(a) || !loop.IsValidActivationTokenId(activation_token_id("query")) {
		t.Fatalf("Invalid or non-unique activation token ids: %#v %#v", a, b)
	}
}

func TestPlaceholderLayout(t *testing.T) {
	tiles := new_tile_geometry(3, 16)
	h := &Handler{tiles: tiles, grid_left: 2}
	h.matches = []*item{
		{entry: &DesktopEntry{Name: "alpha"}, choice: Choice{DesktopID: "a.desktop"}},
		{entry: &DesktopEntry{Name: "bravo"}, choice: Choice{DesktopID: "b.desktop"}},
		{entry: &DesktopEntry{Name: "中文"}, choice: Choice{DesktopID: "x.desktop"}},
	}
	glyph, width, left, ok := h.placeholder_layout(h.matches[0], 10)
	if !ok || glyph != "A" || width != 1 || left != 10+1+(tiles.content_width-3)/2 {
		t.Fatalf("Incorrect placeholder layout: %#v %d %d %v", glyph, width, left, ok)
	}
	if glyph, _, _, _ := h.placeholder_layout(h.matches[2], 0); glyph != "\uf489" {
		t.Fatalf("Incorrect placeholder for a name without a single cell first letter: %#v", glyph)
	}
	// placeholders that do not fit in the tile are not drawn
	h.tiles = new_tile_geometry(7, 8)
	if _, _, _, ok := h.placeholder_layout(h.matches[0], 0); ok {
		t.Fatalf("Placeholder wider than the tile laid out")
	}
	h.tiles = tiles

	// The columns of the parts of placeholders, which are not erased when
	// drawing a line of the grid, as that would erase the whole placeholder
	gr := grid_row{items: []int{0, 1, 2}, tile_height: tiles.height()}
	with_placeholder := []bool{true, false, true}
	if cols := h.placeholder_columns(gr, 1, with_placeholder); cols != nil {
		t.Fatalf("Placeholder columns without support for drawing parts: %v", cols)
	}
	h.text_parts.Supported = true
	expected := [][2]int{}
	for _, c := range []int{0, 2} {
		_, _, left, _ := h.placeholder_layout(h.matches[c], h.grid_left+c*tiles.width())
		expected = append(expected, [2]int{left, left + 3})
	}
	for k := range tiles.height() {
		cols := h.placeholder_columns(gr, k, with_placeholder)
		if k >= 1 && k <= tiles.icon_rows {
			if diff := cmp.Diff(expected, cols); diff != "" {
				t.Fatalf("Incorrect placeholder columns in line %d:\n%s", k, diff)
			}
		} else if cols != nil {
			t.Fatalf("Placeholder columns in line %d: %v", k, cols)
		}
	}
}
