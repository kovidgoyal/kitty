package disk_cache

import (
	"fmt"
	"os"
	"slices"
	"strings"
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
	dc2, err := NewDiskCache(tdir, dc.MaxSize)
	if err != nil {
		t.Fatal(err)
	}

	m := dc.Get("missing", "one", "two")
	if diff := cmp.Diff(m, make(map[string]string)); diff != "" {
		t.Fatalf("Unexpected return from missing: %s", diff)
	}
	dc.Add("k1", map[string][]byte{"1": []byte("abcd"), "2": []byte("efgh")})

	ad := func(key string, expected map[string]string) {
		for _, x := range []*DiskCache{dc, dc2} {
			actual := x.Get(key, utils.Keys(expected)...)

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
	}
	ak := func(keys ...string) {
		for _, x := range []*DiskCache{dc, dc2} {
			kk, err := x.keys()
			if err != nil {
				t.Fatal(err)
			}
			slices.Sort(kk)
			slices.Sort(keys)
			if diff := cmp.Diff(keys, kk); diff != "" {
				t.Fatalf("Unexpected keys: %s", diff)
			}
		}
	}
	ad("k1", map[string]string{"1": "abcd", "2": "efgh"})
	dc.Add("k1", map[string][]byte{"3": []byte("ijk"), "4": []byte("lmo")})
	dc2.Add("k2", map[string][]byte{"1": []byte("123456789")})
	ad("k1", map[string]string{"1": "abcd", "2": "efgh", "3": "ijk"})
	if dc.entries.TotalSize != 14+9 {
		t.Fatalf("TotalSize: %d != %d", dc.entries.TotalSize, 14+9)
	}
	ak("k1", "k2")
	dc.Add("k3", map[string][]byte{"1": []byte(strings.Repeat("a", int(dc.MaxSize)-10))})
	ak("k3", "k2")
	// check that creating a new disk cache prunes
	_, err = NewDiskCache(tdir, dc.MaxSize-8)
	if err != nil {
		t.Fatal(err)
	}
	ak("k3")
}
