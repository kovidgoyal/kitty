package ignorefiles

import (
	"fmt"
	"io/fs"
	"os"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func TestGitignore(t *testing.T) {
	for line, expected := range map[string]struct {
		skipped, negated, only_dirs bool
		parts                       []string
	}{
		"":           {skipped: true},
		" ":          {skipped: true},
		"  ":         {skipped: true},
		"/":          {skipped: true},
		"//":         {skipped: true},
		"# abc":      {skipped: true},
		`\!moose \ `: {parts: []string{`!moose  `}},
		`\#m\oose  `: {parts: []string{`#m\oose`}},
	} {
		p, skipped := CompileGitIgnoreLine(line)
		if skipped != expected.skipped {
			t.Fatalf("skipped: %v != %v for line: %s", expected.skipped, skipped, line)
		}
		if !skipped {
			if p.negated != expected.negated {
				t.Fatalf("negated: %v != %v for line: %s", expected.negated, p.negated, line)
			}
			if p.only_dirs != expected.only_dirs {
				t.Fatalf("only_dirs: %v != %v for line: %s", expected.only_dirs, p.only_dirs, line)
			}
			if diff := cmp.Diff(expected.parts, p.parts); diff != "" {
				t.Fatalf("parts not equal for line: %s\n%s", line, diff)
			}
		}
	}
	type ptest struct {
		path     string
		expected bool
	}
	for _, x := range []struct {
		line  string
		tests []ptest
	}{
		{"foo", []ptest{
			{"foo", true}, {"x/foo", true}, {"foo/x", true},
		}},
		{"/foo", []ptest{
			{"foo", true}, {"x/foo", false},
		}},
		{"doc/frotz/", []ptest{
			{"doc/frotz/", true}, {"a/doc/frotz/", false}, {"doc/frotz", false},
		}},
		{"frotz/", []ptest{
			{"frotz/", true}, {"a/doc/frotz/", true}, {"doc/frotz", false}, {"frotz/", true},
		}},
		{"foo.*", []ptest{
			{"foo.txt", true}, {"foo", false}, {"a/foo.x", true}, {"foo.", true},
		}},

		{"**", []ptest{
			{"foo", true}, {"x/foo", true}, {"foo/x", true},
		}},

		{"**/foo", []ptest{
			{"foo", true}, {"x/foo", true}, {"foo/x", false},
		}},
		{"**/foo/bar", []ptest{
			{"foo", false}, {"x/foo", false}, {"foo/bar", true}, {"a/foo/bar", true}, {"foo/bar/a", false},
		}},
		{"foo/**", []ptest{
			{"foo", false}, {"x/foo", false}, {"foo/bar", true}, {"foo/bar/a", true}, {"foo/bar/a/", true},
		}},
		{"a/**/b", []ptest{
			{"a/b", true}, {"a/x/b", true}, {"a/x/y/b", true}, {"x/a/b", false}, {"a/b/x", false},
		}},
		{"a/**/b/**/c", []ptest{
			{"a/b/c", true}, {"a/x/b/c", true}, {"a/x/y/b/m/n/c", true},
		}},
	} {
		p, skipped := CompileGitIgnoreLine(x.line)
		if skipped {
			t.Fatalf("Unexpectedly failed to compile: %#v", x.line)
		}
		for _, test := range x.tests {
			path := strings.TrimRight(test.path, "/")
			ftype := utils.IfElse(len(path) < len(test.path), fs.ModeDir, 0)
			if actual := p.Match(path, ftype); actual != test.expected {
				t.Fatalf("matched: %v != %v for pattern: %#v and path: %#v", test.expected, actual, x.line, test.path)
			}
		}
	}
	for text, tests := range map[string]map[string]bool{
		``: {"foo": false},
		`
# exclude everything except directory foo/bar
/*
!/foo
/foo/*
!/foo/bar`: {
			"a": true, "foo": false, "foo/x": true, "foo/bar": false, "foo/bar/": false,
		},
		`
**/foo
bar `: {
			"foo": true, "baz/foo": true, "bar": true, "baz/bar": true, "a": false,
		},
		`/*.c`: {"a.c": true, "b/a.c": false},
		`
**/external/**/*.json
**/external/**/.*ignore
**/external/foobar/*.css`: {
			"external/foobar/angular.foo.css": true, "external/barfoo/.gitignore": true, "external/barfoo/.bower.json": true,
		},
		"abc/def\r\nxyz": {"abc/def": true, "a/xyz": true},
		`/**/foo`:        {"foo": true, "foo/": true, "a/b/foo": true, "fooo": false, "ofoo": false},
		"/.js":           {".js": true, ".js/": true, ".js/a": true, ".jsa": false},
		"*.js":           {".js": true, ".js/": true, ".js/a": true, "a.js/a": true, "a.js/a.js": true, ".jsa": false, "a.jsa": false},
		"foo/**/":        {"foo/": false, "foo": false, "foo/abc/": true, "foo/a/b/c/": true, "foo/a": false},
		"foo/**/*.bar":   {"foo/": false, "abc.bar": false, "foo/abc.bar": true, "foo/a.bar/": true, "foo/x/y/z.bar": true},
		`\#abc`:          {"abc": false, "#abc": true},
		"abc\n!abc/x":    {"abc": true, "abc/x": false, "abc/y": true},
		`abc/*`:          {"abc": false, "abc/": false, "abc/x": true},
	} {
		p := NewGitignore()
		if err := p.LoadString(text); err != nil {
			t.Fatal(err)
		}
		for tpath, expected := range tests {
			path := strings.TrimRight(tpath, "/")
			ftype := utils.IfElse(len(path) < len(tpath), fs.ModeDir, 0)
			if actual, _, _ := p.IsIgnored(path, ftype); actual != expected {
				t.Fatalf("ignored: %v != %v for path: %#v and ignorefile:\n%s", expected, actual, tpath, text)
			}
		}
	}
	os.WriteFile(utils.Expanduser("~/.gitconfig"), []byte(`
	[core]
	something
	[else]
	...
	[core]
	...
	[core]
	excludesfile = one
	[core]
	excludesfile = ~/global-gitignore
`), 0600)
	if ef := get_global_gitconfig_excludesfile(); ef != utils.Expanduser("~/global-gitignore") {
		t.Fatalf("global gitconfig excludes file incorrect: %s != %s", utils.Expanduser("~/global-gitignore"), ef)
	}
}
