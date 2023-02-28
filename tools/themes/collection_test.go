// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

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

	buf := bytes.Buffer{}
	zw := zip.NewWriter(&buf)
	fw, _ := zw.Create("x/themes.json")
	fw.Write([]byte(`[
    {
        "author": "X Y",
        "blurb": "A dark color scheme for the kitty terminal.",
        "file": "themes/Alabaster_Dark.conf",
        "is_dark": true,
        "license": "MIT",
        "name": "Alabaster Dark",
        "num_settings": 30,
        "upstream": "https://xxx.com"
    },
	{
		"name": "Empty", "file": "empty.conf"
	}
	]`))
	fw, _ = zw.Create("x/empty.conf")
	fw.Write([]byte("empty"))
	fw, _ = zw.Create("x/themes/Alabaster_Dark.conf")
	fw.Write([]byte("alabaster"))
	zw.Close()

	received_etag := ""
	request_count := 0
	check_etag := true
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		request_count++
		received_etag = r.Header.Get("If-None-Match")
		if check_etag && received_etag == `"xxx"` {
			w.WriteHeader(http.StatusNotModified)
			return
		}
		w.Header().Add("ETag", `"xxx"`)
		w.Write(buf.Bytes())
	}))
	defer ts.Close()

	_, err := fetch_cached("test", ts.URL, tdir, 0)
	if err != nil {
		t.Fatal(err)
	}
	r, err := zip.OpenReader(filepath.Join(tdir, "test.zip"))
	if err != nil {
		t.Fatal(err)
	}
	var jm JSONMetadata
	err = json.Unmarshal([]byte(r.Comment), &jm)
	if err != nil {
		t.Fatal(err)
	}
	if jm.Etag != `"xxx"` {
		t.Fatalf("Unexpected ETag: %#v", jm.Etag)
	}
	_, err = fetch_cached("test", ts.URL, tdir, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if request_count != 1 {
		t.Fatal("Cached zip file was not used")
	}
	before, _ := os.Stat(filepath.Join(tdir, "test.zip"))
	_, err = fetch_cached("test", ts.URL, tdir, 0)
	if err != nil {
		t.Fatal(err)
	}
	if request_count != 2 {
		t.Fatal("Cached zip file was incorrectly used")
	}
	if received_etag != `"xxx"` {
		t.Fatalf("Got invalid ETag: %#v", received_etag)
	}
	after, _ := os.Stat(filepath.Join(tdir, "test.zip"))
	if before.ModTime() != after.ModTime() {
		t.Fatal("Cached zip file was incorrectly re-downloaded")
	}
	err = os.Chtimes(filepath.Join(tdir, "test.zip"), time.Time{}, time.Time{})
	if err != nil {
		t.Fatal(err)
	}
	before, _ = os.Stat(filepath.Join(tdir, "test.zip"))
	check_etag = false
	_, err = fetch_cached("test", ts.URL, tdir, 0)
	if err != nil {
		t.Fatal(err)
	}
	after, _ = os.Stat(filepath.Join(tdir, "test.zip"))
	if before.ModTime() == after.ModTime() {
		t.Fatalf("Cached zip file was incorrectly not re-downloaded. %#v == %#v", before.ModTime(), after.ModTime())
	}
	coll := Themes{name_map: map[string]*Theme{}}
	closer, err := coll.add_from_zip_file(filepath.Join(tdir, "test.zip"))
	if err != nil {
		t.Fatal(err)
	}
	defer closer.Close()
	if code, err := coll.ThemeByName("Empty").load_code(); code != "empty" {
		if err != nil {
			t.Fatal(err)
		}
		t.Fatal("failed to load code for empty theme")
	}
	if code, err := coll.ThemeByName("Alabaster Dark").load_code(); code != "alabaster" {
		if err != nil {
			t.Fatal(err)
		}
		t.Fatal("failed to load code for alabaster theme")
	}
}
