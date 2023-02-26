// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestThemeCollections(t *testing.T) {
	for fname, expected := range map[string]string{
		"moose":    "Moose",
		"mooseCat": "Moose Cat",
		"a_bC":     "A B C",
	} {
		actual := theme_name_from_file_name(fname)
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Unexpected theme name for %s:\n%s", fname, diff)
		}
	}

	tdir := t.TempDir()

	pt := func(expected ThemeMetadata, lines ...string) {
		os.WriteFile(filepath.Join(tdir, "temp.conf"), []byte(strings.Join(lines, "\n")), 0o600)
		actual, _, err := parse_theme_metadata(filepath.Join(tdir, "temp.conf"))
		if err != nil {
			t.Fatal(err)
		}
		if diff := cmp.Diff(&expected, actual); diff != "" {
			t.Fatalf("Failed to parse:\n%s\n\n%s", strings.Join(lines, "\n"), diff)
		}
	}
	pt(ThemeMetadata{Name: "XYZ", Blurb: "a b", Author: "A", Is_dark: true, Num_settings: 2},
		"# some crap", " ", "## ", "## author: A", "## name: XYZ", "## blurb: a", "## b", "", "color red", "background black", "include inc.conf")
	os.WriteFile(filepath.Join(tdir, "inc.conf"), []byte("background white"), 0o600)
	pt(ThemeMetadata{Name: "XYZ", Blurb: "a b", Author: "A", Num_settings: 2},
		"# some crap", " ", "## ", "## author: A", "## name: XYZ", "## blurb: a", "## b", "", "color red", "background black", "include inc.conf")
}
