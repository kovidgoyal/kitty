// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"fmt"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestFTCSerialization(t *testing.T) {
	ftc := FileTransmissionCommand{}
	q := func(expected string) {
		actual := ftc.Serialize()
		if diff := cmp.Diff(expected, actual); diff != "" {
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
}
