package disk_cache

import (
	"fmt"
	"os"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func TestDiskCache(t *testing.T) {
	tdir := t.TempDir()
	dc, err := NewDiskCache(tdir, 64)
	if err != nil {
		t.Fatal(err)
	}
	m := dc.Get("missing", "one", "two")
	if diff := cmp.Diff(m, make(map[string]string)); diff != "" {
		t.Fatalf("Unexpected return from missing: %s", diff)
	}
	dc.Add("k1", map[string][]byte{"1": []byte("abcd"), "2": []byte("efgh")})

	ad := func(key string, expected map[string]string) {
		actual := dc.Get(key, utils.Keys(expected)...)

		for k, path := range actual {
			d, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			actual[k] = string(d)
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Data for %s not equal: %s", key, diff)
		}
	}
	ad("k1", map[string]string{"1": "abcd", "2": "efgh"})
}
