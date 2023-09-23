// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"crypto/rand"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"reflect"
	"testing"
)

var _ = fmt.Print

func TestSHM(t *testing.T) {
	data := make([]byte, 13347)
	_, _ = rand.Read(data)
	mm, err := CreateTemp("test-kitty-shm-", uint64(len(data)))
	if err != nil {
		t.Fatal(err)
	}

	copy(mm.Slice(), data)
	err = mm.Flush()
	if err != nil {
		t.Fatalf("Failed to msync() with error: %v", err)
	}
	err = mm.Close()
	if err != nil {
		t.Fatalf("Failed to close with error: %v", err)
	}

	g, err := Open(mm.Name(), uint64(len(data)))
	if err != nil {
		t.Fatal(err)
	}
	data2 := g.Slice()
	if !reflect.DeepEqual(data, data2) {
		t.Fatalf("Could not read back written data: Written data length: %d Read data length: %d", len(data), len(data2))
	}
	err = g.Close()
	if err != nil {
		t.Fatalf("Failed to close with error: %v", err)
	}
	err = g.Unlink()
	if err != nil {
		t.Fatalf("Failed to unlink with error: %v", err)
	}
	g, err = Open(mm.Name(), uint64(len(data)))
	if err == nil {
		t.Fatalf("Unlinking failed could re-open the SHM data. Data equal: %v Data length: %d", reflect.DeepEqual(g.Slice(), data), len(g.Slice()))
	}
	if mm.IsFileSystemBacked() {
		_, err = os.Stat(mm.FileSystemName())
		if !errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("Unlinking %s did not work", mm.Name())
		}
	}
}
