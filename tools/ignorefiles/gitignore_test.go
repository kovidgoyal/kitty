package ignorefiles

import (
	"fmt"
	"io/fs"
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
}
