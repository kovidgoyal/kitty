// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package config

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestConfigParsing(t *testing.T) {
	tdir := t.TempDir()
	conf_file := filepath.Join(tdir, "a.conf")
	os.Mkdir(filepath.Join(tdir, "sub"), 0o700)
	os.WriteFile(conf_file, []byte(
		`error main
# ignore me
a one
#: other
include sub/b.conf
b
include non-existent
globinclude sub/c?.conf
`), 0o600)
	os.WriteFile(filepath.Join(tdir, "sub/b.conf"), []byte("incb cool\ninclude a.conf"), 0o600)
	os.WriteFile(filepath.Join(tdir, "sub/c1.conf"), []byte("inc1 cool"), 0o600)
	os.WriteFile(filepath.Join(tdir, "sub/c2.conf"), []byte("inc2 cool\nenvinclude ENVINCLUDE"), 0o600)
	os.WriteFile(filepath.Join(tdir, "sub/c.conf"), []byte("inc notcool\nerror sub"), 0o600)

	var parsed_lines []string
	pl := func(key, val string) error {
		if key == "error" {
			return fmt.Errorf("%s", val)
		}
		parsed_lines = append(parsed_lines, key+" "+val)
		return nil
	}

	p := ConfigParser{LineHandler: pl, override_env: []string{"ENVINCLUDE=env cool\ninclude c.conf"}}
	err := p.ParseFiles(conf_file)
	if err != nil {
		t.Fatal(err)
	}
	err = p.ParseOverrides("over one", "over two")
	diff := cmp.Diff([]string{"a one", "incb cool", "b ", "inc1 cool", "inc2 cool", "env cool", "inc notcool", "over one", "over two"}, parsed_lines)
	if diff != "" {
		t.Fatalf("Unexpected parsed config values:\n%s", diff)
	}
	bad_lines := []string{}
	for _, bl := range p.BadLines() {
		bad_lines = append(bad_lines, fmt.Sprintf("%s: %d", filepath.Base(bl.Src_file), bl.Line_number))
	}
	diff = cmp.Diff([]string{"a.conf: 1", "c.conf: 2"}, bad_lines)
	if diff != "" {
		t.Fatalf("Unexpected bad lines:\n%s", diff)
	}
}
