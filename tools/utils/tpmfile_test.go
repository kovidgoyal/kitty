// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"runtime"
	"strconv"
	"testing"
)

var _ = fmt.Print

func TestCreateAnonymousTempfile(t *testing.T) {
	f, err := CreateAnonymousTemp("")
	if err != nil {
		t.Fatal(err)
	}
	fd := int64(f.Fd())
	f.Close()
	if runtime.GOOS == "linux" {
		if f.Name() != "/proc/self/fd/"+strconv.FormatInt(fd, 10) {
			t.Fatalf("Anonymous tempfile was not created atomically")
		}
	}
}
