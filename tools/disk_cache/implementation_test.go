package disk_cache

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime/debug"
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
	arc := func(dc *DiskCache, expected int) {
		if expected != dc.read_count {
			t.Fatalf("disk cache has unexpected read count: %d != %d\n%s", expected, dc.read_count, debug.Stack())
		}
	}

	m, err := dc.Get("missing", "one", "two")
	if err != nil {
		t.Fatal(err)
	}
	if len(m) > 0 {
		t.Fatalf("Unexpected return from missing: %s", m)
	}
	dc.Add("k1", map[string][]byte{"1": []byte("abcd"), "2": []byte("efgh")})
	arc(dc, 0)

	ad := func(key string, expected map[string]string) {
		for _, x := range []*DiskCache{dc, dc2} {
			actual, err := x.Get(key, utils.Keys(expected)...)
			if err != nil {
				t.Fatal(err)
			}

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
		for i, x := range []*DiskCache{dc, dc2} {
			kk, err := x.keys()
			if err != nil {
				t.Fatal(err)
			}
			if diff := cmp.Diff(keys, kk); diff != "" {
				t.Fatalf("wrong keys in %d: %s", i+1, diff)
			}
		}
	}
	ad("k1", map[string]string{"1": "abcd", "2": "efgh"})
	arc(dc, 0)
	arc(dc2, 1)
	dc.Add("k1", map[string][]byte{"3": []byte("ijk"), "4": []byte("lmo")})
	arc(dc, 1) // because dc2.Get() will have updated the file
	arc(dc2, 1)
	ak("k1")
	dc2.Add("k2", map[string][]byte{"1": []byte("123456789")})
	arc(dc, 1)
	arc(dc2, 2)
	ak("k1", "k2")
	ad("k1", map[string]string{"1": "abcd", "2": "efgh", "3": "ijk"})
	if dc.entries.TotalSize != 14+9 {
		t.Fatalf("TotalSize: %d != %d", dc.entries.TotalSize, 14+9)
	}
	arc(dc, 2)  // dc2.Add()
	arc(dc2, 3) // dc.Get()
	ak("k2", "k1")
	dc.Get("k2")
	arc(dc, 3) // dc2.Get()
	arc(dc2, 3)
	ak("k1", "k2")
	dc.Add("k3", map[string][]byte{"1": []byte(strings.Repeat("a", int(dc.MaxSize)-10))})
	arc(dc, 3)
	ak("k2", "k3")
	// check that creating a new disk cache prunes
	_, err = NewDiskCache(tdir, dc.MaxSize-8)
	if err != nil {
		t.Fatal(err)
	}
	ak("k3")
	arc(dc, 4) // NewDiskCache()

	// test the path api
	path := filepath.Join(tdir, "source")
	if err = os.WriteFile(path, []byte("abcdfjrof"), 0o600); err != nil {
		t.Fatal(err)
	}
	key, _, err := dc.GetPath(path)
	if _, err = dc.AddPath(path, key, map[string][]byte{"1": []byte("1")}); err != nil {
		t.Fatal(err)
	}
	_, _, entries_before, _ := dc.entries_from_folders()
	if diff := cmp.Diff(1, len(dc.entries.PathMap)); diff != "" {
		t.Fatalf("unexpected pathmap count: %s", diff)
	}
	if err = os.WriteFile(path, []byte("changed contents"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err = dc.AddPath(path, key, map[string][]byte{"1": []byte("2")}); err != nil {
		t.Fatal(err)
	}
	if diff := cmp.Diff(1, len(dc.entries.PathMap)); diff != "" {
		t.Fatalf("unexpected pathmap count: %s", diff)
	}
	_, _, entries_after, _ := dc.entries_from_folders()
	if len(entries_before) != len(entries_after) {
		t.Fatalf("unexpected entries: %s", entries_after)
	}
	arc(dc, 4)
}
