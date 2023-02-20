// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"kitty/tools/utils/shm"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestCloneEnv(t *testing.T) {
	env := map[string]string{"a": "1", "b": "2"}
	data, err := json.Marshal(env)
	if err != nil {
		t.Fatal(err)
	}
	mmap, err := shm.CreateTemp("", 128)
	if err != nil {
		t.Fatal(err)
	}
	defer mmap.Unlink()
	copy(mmap.Slice()[4:], data)
	binary.BigEndian.PutUint32(mmap.Slice(), uint32(len(data)))
	mmap.Close()
	x, err := add_cloned_env(mmap.Name())
	if err != nil {
		t.Fatal(err)
	}
	diff := cmp.Diff(env, x)
	if diff != "" {
		t.Fatalf("Failed to deserialize env\n%s", diff)
	}
}
