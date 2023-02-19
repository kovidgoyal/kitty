// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"fmt"
	"testing"
)

var _ = fmt.Print

func TestGetSSHOptions(t *testing.T) {
	m := SSHOptions()
	if m["w"] != "local_tun[:remote_tun]" {
		t.Fatalf("Unexpected set of SSH options: %#v", m)
	}
}
