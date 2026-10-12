// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// When the kitty checkout lives under a directory whose name contains a
// space (a common occurrence on macOS, e.g. "Desktop/My Projects/kitty"),
// pkg-config tokenizes the Cflags/Libs lines it emits on unescaped
// whitespace. If relocate_pkgconfig writes the new, real prefix into a .pc
// file without escaping spaces, pkg-config truncates the path at the first
// space and the build fails with errors such as "hb.h file not found".
func TestRelocatePkgconfigEscapesSpacesInPcFiles(t *testing.T) {
	dir := t.TempDir()
	pc_path := filepath.Join(dir, "harfbuzz.pc")
	old_prefix := "/sw/sw"
	new_prefix := "/Users/someone/has space/kitty/dependencies/darwin-amd64"
	contents := "prefix=" + old_prefix + "\nincludedir=${prefix}/include\n\nName: harfbuzz\nCflags: -I${includedir}/harfbuzz\n"
	if err := os.WriteFile(pc_path, []byte(contents), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := relocate_pkgconfig(pc_path, old_prefix, new_prefix); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(pc_path)
	if err != nil {
		t.Fatal(err)
	}
	expected_prefix_line := `prefix=/Users/someone/has\ space/kitty/dependencies/darwin-amd64`
	if !strings.Contains(string(raw), expected_prefix_line) {
		t.Fatalf("space in new prefix was not escaped in .pc file, got:\n%s", raw)
	}

	// The same function is also used to relocate paths embedded in
	// Python's _sysconfigdata_*.py, which is a plain Python string literal,
	// not something pkg-config tokenizes. Escaping the space there would
	// corrupt the path, so it must be left untouched.
	py_path := filepath.Join(dir, "_sysconfigdata_darwin.py")
	if err := os.WriteFile(py_path, []byte("prefix = '"+old_prefix+"'\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := relocate_pkgconfig(py_path, old_prefix, new_prefix); err != nil {
		t.Fatal(err)
	}
	raw, err = os.ReadFile(py_path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(raw), "prefix = '"+new_prefix+"'") {
		t.Fatalf("plain (non pkg-config) relocation should not escape spaces, got:\n%s", raw)
	}
}
