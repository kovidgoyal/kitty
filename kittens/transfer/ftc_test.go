// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestFTCSerialization(t *testing.T) {
	ftc := FileTransmissionCommand{}
	q := func(expected string) {
		actual := ftc.Serialize()
		ad := make(map[string]bool)
		for _, x := range strings.Split(actual, ";") {
			ad[x] = true
		}
		ed := make(map[string]bool)
		for _, x := range strings.Split(expected, ";") {
			ed[x] = true
		}
		if diff := cmp.Diff(ed, ad); diff != "" {
			t.Fatalf("Failed to Serialize:\n%s", diff)
		}
	}
	q("")
	ftc.Action = Action_send
	q("ac=send")
	ftc.File_id = "fid"
	ftc.Name = "moose"
	ftc.Mtime = time.Second
	ftc.Permissions = 0o600
	ftc.Data = []byte("moose")
	q("ac=send;fid=fid;n=bW9vc2U;mod=1000000000;prm=384;d=bW9vc2U")
	n, err := NewFileTransmissionCommand(ftc.Serialize())
	if err != nil {
		t.Fatal(err)
	}
	q(n.Serialize())

	unsafe := "moo\x1b;;[?*.-se1"
	if safe_string(unsafe) != "moo.-se1" {
		t.Fatalf("safe_string() failed for %#v yielding: %#v", unsafe, safe_string(unsafe))
	}
}
