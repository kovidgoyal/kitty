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
		actual := ThemeNameFromFileName(fname)
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Unexpected theme name for %s:\n%s", fname, diff)
		}
	}

	tdir := t.TempDir()

	pt := func(expected ThemeMetadata, lines ...string) {
		if err := os.WriteFile(filepath.Join(tdir, "temp.conf"), []byte(strings.Join(lines, "\n")), 0o600); err != nil {
			t.Fatal(err)
		}
		actual, _, err := ParseThemeMetadata(filepath.Join(tdir, "temp.conf"))
		if err != nil {
			t.Fatal(err)
		}
		if diff := cmp.Diff(&expected, actual); diff != "" {
			t.Fatalf("Failed to parse:\n%s\n\n%s", strings.Join(lines, "\n"), diff)
		}
	}
	pt(ThemeMetadata{Name: "XYZ", Blurb: "a b", Author: "A", Is_dark: true, Num_settings: 2},
		"# some crap", " ", "## ", "## author: A", "## name: XYZ", "## blurb: a", "## b", "", "color red", "background black", "include inc.conf")
	if err := os.WriteFile(filepath.Join(tdir, "inc.conf"), []byte("background white"), 0o600); err != nil {
		t.Fatal(err)
	}
	pt(ThemeMetadata{Name: "XYZ", Blurb: "a b", Author: "A", Num_settings: 2},
		"# some crap", " ", "## ", "## author: A", "## name: XYZ", "## blurb: a", "## b", "", "color red", "background black", "include inc.conf")

	buf := bytes.Buffer{}
	zw := zip.NewWriter(&buf)
	fw, _ := zw.Create("x/themes.json")
	if _, err := fw.Write([]byte(`[
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
	]`)); err != nil {
		t.Fatal(err)
	}
	fw, _ = zw.Create("x/empty.conf")
	if _, err := fw.Write([]byte("empty")); err != nil {
		t.Fatal(err)
	}
	fw, _ = zw.Create("x/themes/Alabaster_Dark.conf")
	if _, err := fw.Write([]byte("alabaster")); err != nil {
		t.Fatal(err)
	}
	zw.Close()

	received_etag := ""
	request_count := 0
	send_count := 0
	check_etag := true
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		request_count++
		received_etag = r.Header.Get("If-None-Match")
		if check_etag && received_etag == `"xxx"` {
			w.WriteHeader(http.StatusNotModified)
			return
		}
		send_count++
		w.Header().Add("ETag", `"xxx"`)
		w.Write(buf.Bytes())
	}))
	defer ts.Close()

	if _, err := fetch_cached("test", ts.URL, tdir, 0); err != nil {
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
		t.Fatalf("Cached zip file was not used: %d", request_count)
	}
	_, err = fetch_cached("test", ts.URL, tdir, 0)
	if err != nil {
		t.Fatal(err)
	}
	if request_count != 2 {
		t.Fatalf("Cached zip file was incorrectly used: %d", request_count)
	}
	if received_etag != `"xxx"` {
		t.Fatalf("Got invalid ETag: %#v", received_etag)
	}
	if send_count != 1 {
		t.Fatalf("Cached zip file was incorrectly re-downloaded: %d", send_count)
	}
	check_etag = false
	_, err = fetch_cached("test", ts.URL, tdir, 0)
	if err != nil {
		t.Fatal(err)
	}
	if send_count != 2 {
		t.Fatalf("Cached zip file was incorrectly not re-downloaded. %d", send_count)
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
