// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package hints

import (
	"errors"
	"fmt"
	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/utils"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestHintMarking(t *testing.T) {

	var opts *Options
	cols := 20
	cli_args := []string{}

	reset := func() {
		opts = &Options{Type: "url", UrlPrefixes: "default", Regex: kitty.HintsDefaultRegex}
		cols = 20
		cli_args = []string{}
	}

	r := func(text string, url ...string) (marks []Mark) {
		ptext := convert_text(text, cols)
		ptext, marks, _, err := find_marks(ptext, opts, cli_args...)
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
		for _, m := range marks {
			q := strings.NewReplacer("\n", "", "\r", "", "\x00", "").Replace(ptext[m.Start:m.End])
			if diff := cmp.Diff(m.Text, q); diff != "" {
				t.Fatalf("Mark start (%d) and end (%d) dont point to correct offset in text for %#v\n%s", m.Start, m.End, text, diff)
			}
		}
		return
	}

	reset()
	u := `http://test.me/`
	r(u, u)
	r(u+"#fragme", u+"#fragme")
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
		_, marks, _, err := find_marks(ptext, opts, cli_args...)
		if err != nil {
			t.Fatalf("%#v failed with error: %s", text, err)
		}
		gd := map[string]any{"path": path, "line": strconv.Itoa(line)}
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

	reset()
	opts.Type = "path"
	r("file.c", "file.c")
	r("file.c.", "file.c")
	r("file.epub.", "file.epub")
	r("(file.epub)", "file.epub")
	r("some/path", "some/path")

	reset()
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

	reset()
	opts.Type = "regex"
	opts.Regex = `(?ms)^[*]?\s(\S+)`
	r(`* 2b687c2 - test1`, `2b687c2`)
	opts.Regex = `(?<=got:    )sha256.{4}`
	r(`got:    sha256-L8=`, `sha256-L8=`)

	reset()
	opts.Type = "word"
	r(`#one (two) 😍 a-1b `, `#one`, `two`, `a-1b`)
	r("fōtiz час a\u0310b ", `fōtiz`, `час`, "a\u0310b")

	reset()
	tdir := t.TempDir()
	simple := filepath.Join(tdir, "simple.py")
	cli_args = []string{"--customize-processing", simple, "extra1"}
	os.WriteFile(simple, []byte(`
def mark(text, args, Mark, extra_cli_args, *a):
    import re
    for idx, m in enumerate(re.finditer(r'\w+', text)):
        start, end = m.span()
        mark_text = text[start:end].replace('\n', '').replace('\0', '')
        yield Mark(idx, start, end, mark_text, {"idx": idx, "args": extra_cli_args})
`), 0o600)
	opts.Type = "regex"
	opts.CustomizeProcessing = simple
	marks := r("漢字 b", `漢字`, `b`)
	if diff := cmp.Diff(marks[0].Groupdict, map[string]any{"idx": float64(0), "args": []any{"extra1"}}); diff != "" {
		t.Fatalf("Did not get expected groupdict from custom processor:\n%s", diff)
	}
	opts.Regex = "b"
	os.WriteFile(simple, []byte(""), 0o600)
	r("a b", `b`)
}
