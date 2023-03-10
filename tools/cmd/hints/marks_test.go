// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package hints

import (
	"errors"
	"fmt"
	"kitty"
	"kitty/tools/utils"
	"strconv"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestHintMarking(t *testing.T) {

	opts := &Options{Type: "url", UrlPrefixes: "default", Regex: kitty.HintsDefaultRegex}
	cols := 20
	r := func(text string, url ...string) {
		ptext := convert_text(text, cols)
		_, marks, _, err := find_marks(ptext, opts)
		if err != nil {
			var e *ErrNoMatches
			if len(url) != 0 || !errors.As(err, &e) {
				t.Fatalf("%#v failed with error: %s", text, err)
			}
			return
		}
		actual := utils.Map(func(m Mark) string { return m.Text }, marks)
		if diff := cmp.Diff(url, actual); diff != "" {
			t.Fatalf("%#v failed:\n%s", text, diff)
		}
	}

	u := `http://test.me/`
	r(u, u)
	r(`"`+u+`"`, u)
	r("("+u+")", u)
	cols = len(u)
	r(u+"\nxxx", u+"xxx")
	cols = 20
	r("link:"+u+"[xxx]", u)
	r("`xyz <"+u+">`_.", u)
	r(`<a href="`+u+`">moo`, u)
	r("\x1b[mhttp://test.me/1234\n\x1b[mx", "http://test.me/1234")
	r("\x1b[mhttp://test.me/12345\r\x1b[m6\n\x1b[mx", "http://test.me/123456")

	opts.Type = "linenum"
	m := func(text, path string, line int) {
		ptext := convert_text(text, cols)
		_, marks, _, err := find_marks(ptext, opts)
		if err != nil {
			t.Fatalf("%#v failed with error: %s", text, err)
		}
		gd := map[string]string{"path": path, "line": strconv.Itoa(line)}
		if diff := cmp.Diff(marks[0].Groupdict, gd); diff != "" {
			t.Fatalf("%#v failed:\n%s", text, diff)
		}
	}
	m("file.c:23", "file.c", 23)
	m("file.c:23:32", "file.c", 23)
	m("file.cpp:23:1", "file.cpp", 23)
	m("a/file.c:23", "a/file.c", 23)
	m("a/file.c:23:32", "a/file.c", 23)
	m("~/file.c:23:32", utils.Expanduser("~/file.c"), 23)

	opts.Type = "path"
	r("file.c", "file.c")
	r("file.c.", "file.c")
	r("file.epub.", "file.epub")
	r("(file.epub)", "file.epub")
	r("some/path", "some/path")

	cols = 60
	opts.Type = "ip"
	r(`100.64.0.0`, `100.64.0.0`)
	r(`2001:0db8:0000:0000:0000:ff00:0042:8329`, `2001:0db8:0000:0000:0000:ff00:0042:8329`)
	r(`2001:db8:0:0:0:ff00:42:8329`, `2001:db8:0:0:0:ff00:42:8329`)
	r(`2001:db8::ff00:42:8329`, `2001:db8::ff00:42:8329`)
	r(`2001:DB8::FF00:42:8329`, `2001:DB8::FF00:42:8329`)
	r(`0000:0000:0000:0000:0000:0000:0000:0001`, `0000:0000:0000:0000:0000:0000:0000:0001`)
	r(`::1`, `::1`)
	r(`255.255.255.256`)
	r(`:1`)

}
