// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package shm

import (
	"errors"
	"fmt"
	"io/fs"
	"math/rand"
	"os"
	"reflect"
	"testing"
)

var _ = fmt.Print

func TestSHM(t *testing.T) {
	data := make([]byte, 13347)
	rand.Read(data)
	mm, err := CreateTemp("test-kitty-shm-", uint64(len(data)))
	if err != nil {
		t.Fatal(err)
	}

	copy(mm.Slice(), data)
	mm.Close()

	g, err := Open(mm.Name())
	if err != nil {
		t.Fatal(err)
	}
	data2 := g.Slice()
	if !reflect.DeepEqual(data, data2) {
		t.Fatalf("Could not read back written data: Written data length: %d Read data length: %d", len(data), len(data2))
	}
	g.Close()
	g.Unlink()
	_, err = os.Stat(mm.Name())
	if !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("Unlinking %s did not work", mm.Name())
	}

}
