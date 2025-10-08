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
	ensure_entries := func() {
		for _, x := range []*DiskCache{dc, dc2} {
			if err = x.ensure_entries(); err != nil {
				t.Fatal(err)
			}
		}

	}
	arc := func(counts ...int) {
		ensure_entries()
		if diff := cmp.Diff(counts, []int{dc.read_count, dc2.read_count}); diff != "" {
			t.Fatalf("disk cache has unexpected read count\n%s\n%s", diff, debug.Stack())
		}
	}
	add := func(dc *DiskCache, key string, data map[string]string) {
		d := make(map[string][]byte, len(data))
		for k, v := range data {
			d[k] = []byte(v)
		}
		if _, err := dc.Add(key, d); err != nil {
			t.Fatal(err)
		}
		ensure_entries()
	}

	m, err := dc.Get("missing", "one", "two")
	if err != nil {
		t.Fatal(err)
	}
	if len(m) > 0 {
		t.Fatalf("Unexpected return from missing: %s", m)
	}

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
			ensure_entries()
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
		ensure_entries()
	}
	add(dc, "k1", map[string]string{"1": "abcd", "2": "efgh"})
	arc(0, 1)
	ad("k1", map[string]string{"1": "abcd", "2": "efgh"})
	arc(1, 2) // the two gets cause two updates
	add(dc, "k1", map[string]string{"3": "ijk", "4": "lmo"})
	arc(1, 3) // dc.Add() causes re-read in dc2
	ak("k1")
	arc(1, 3)
	add(dc2, "k2", map[string]string{"1": "123456789"})
	arc(2, 3) // dc2.Add() causes re-read in dc
	ak("k1", "k2")
	arc(2, 3)
	ad("k1", map[string]string{"1": "abcd", "2": "efgh", "3": "ijk"})
	if dc.entries.TotalSize != 14+9 {
		t.Fatalf("TotalSize: %d != %d", dc.entries.TotalSize, 14+9)
	}
	arc(3, 4) // the two gets cause two updates
	ak("k2", "k1")
	dc.Get("k2")
	arc(3, 5) // dc.Get() causes dc2 to read
	ak("k1", "k2")
	add(dc, "k3", map[string]string{"1": strings.Repeat("a", int(dc.MaxSize)-10)})
	arc(3, 6) // dc.Add() causes dc2 to read
	ak("k2", "k3")
	// check that creating a new disk cache prunes
	_, err = NewDiskCache(tdir, dc.MaxSize-8)
	if err != nil {
		t.Fatal(err)
	}
	ak("k3")
	arc(4, 7) // NewDiskCache()

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
	arc(4, 8) // dc.AddPath() causes dc2 to read
}
