// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"os"
	"os/exec"
	"testing"
)

var _ = fmt.Print

func TestFileLock(t *testing.T) {
	tdir := t.TempDir()

	file_descriptor, err := os.Open(tdir)
	if err != nil {
		t.Fatalf("Initial open of %s failed with error: %s", tdir, err)
	}
	if err = LockFileExclusive(file_descriptor); err != nil {
		file_descriptor.Close()
		t.Fatalf("Initial lock of %s failed with error: %s", tdir, err)
	}
	defer func() {
		_ = UnlockFile(file_descriptor)
		file_descriptor.Close()
	}()
	cmd := exec.Command(KittyExe(), "+runpy", `
import sys, os, fcntl
fd = os.open(sys.argv[-1], os.O_RDONLY)
try:
	fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(0)
else:
	print("Lock unexpectedly succeeded", flush=True)
	sys.exit(1)
`, tdir)
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("Lock test process failed with error: %s and output:\n%s", err, string(output))
	}
}
