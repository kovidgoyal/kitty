package disk_cache

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime/debug"
	"strings"
	"sync"
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

func TestDiskCacheLock(t *testing.T) {
	dc, err := NewDiskCache(t.TempDir(), 64)
	if err != nil {
		t.Fatal(err)
	}
	if err = dc.lock(); err != nil {
		t.Fatal(err)
	}
	defer dc.unlock()
	if dc.lock_mutex.TryLock() {
		dc.lock_mutex.Unlock()
		t.Fatal("cache mutex released before the cache operation finished")
	}
}

func TestDiskCacheConcurrentGet(t *testing.T) {
	dc, err := NewDiskCache(t.TempDir(), 64)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = dc.Add("sharedkey", map[string][]byte{"data": []byte("cached")}); err != nil {
		t.Fatal(err)
	}
	var workers sync.WaitGroup
	start := make(chan struct{})
	for range 6 {
		workers.Go(func() {
			<-start
			for range 8 {
				paths, err := dc.Get("sharedkey", "data")
				if err != nil {
					t.Error(err)
					return
				}
				if paths["data"] == "" {
					t.Error("concurrent Get lost cached data")
					return
				}
				if data, err := os.ReadFile(paths["data"]); err != nil || string(data) != "cached" {
					t.Errorf("path returned by concurrent Get is not readable: %q, %v", data, err)
					return
				}
			}
		})
	}
	close(start)
	workers.Wait()
}

func TestDiskCacheExportReplacesAtomically(t *testing.T) {
	dc, err := NewDiskCache(t.TempDir(), 0)
	if err != nil {
		t.Fatal(err)
	}
	paths, err := dc.Add("key", map[string][]byte{"data": []byte("old")})
	if err != nil {
		t.Fatal(err)
	}
	exported := paths["data"]
	// a Get of unchanged data must not touch the previously exported path
	before, err := os.Stat(exported)
	if err != nil {
		t.Fatal(err)
	}
	if paths, err = dc.Get("key", "data"); err != nil || paths["data"] != exported {
		t.Fatalf("Get returned unexpected paths: %v, %v", paths, err)
	}
	if after, err := os.Stat(exported); err != nil || !os.SameFile(before, after) {
		t.Fatalf("Get replaced an already exported file: %v", err)
	}
	// updated data must replace the exported path, leaving no temp files
	if paths, err = dc.Add("key", map[string][]byte{"data": []byte("new")}); err != nil || paths["data"] != exported {
		t.Fatalf("Add returned unexpected paths: %v, %v", paths, err)
	}
	if data, err := os.ReadFile(exported); err != nil || string(data) != "new" {
		t.Fatalf("exported file not updated: %q, %v", data, err)
	}
	entries, err := os.ReadDir(dc.ResultsDir())
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Fatalf("unexpected files in results dir: %v", entries)
	}
}

func TestDiskCacheGetUntrackedKey(t *testing.T) {
	dc, err := NewDiskCache(t.TempDir(), 64)
	if err != nil {
		t.Fatal(err)
	}
	// simulate a key folder that is missing from entries.json
	base := dc.folder_for_key("untracked")
	if err = os.MkdirAll(base, 0o700); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(base, "data"), []byte("orphan"), 0o600); err != nil {
		t.Fatal(err)
	}
	paths, err := dc.Get("untracked", "data")
	if err != nil {
		t.Fatal(err)
	}
	if data, err := os.ReadFile(paths["data"]); err != nil || string(data) != "orphan" {
		t.Fatalf("could not read untracked key: %q, %v", data, err)
	}
}

func TestDiskCacheLockErrors(t *testing.T) {
	source := filepath.Join(t.TempDir(), "source")
	if err := os.WriteFile(source, []byte("source"), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name string
		run  func(*DiskCache) error
		// whether run() locks dc itself, rather than some other DiskCache
		uses_dc bool
	}{
		{"Get", func(dc *DiskCache) error {
			_, err := dc.Get("key", "data")
			return err
		}, true},
		{"GetPath", func(dc *DiskCache) error {
			_, _, err := dc.GetPath(source, "data")
			return err
		}, true},
		{"Remove", func(dc *DiskCache) error { return dc.Remove("key") }, true},
		{"Clear", func(dc *DiskCache) error { return dc.Clear() }, true},
		{"AddPath", func(dc *DiskCache) error {
			_, err := dc.AddPath(source, "key", map[string][]byte{"data": []byte("updated")})
			return err
		}, true},
		{"Add", func(dc *DiskCache) error {
			_, err := dc.Add("key", map[string][]byte{"data": []byte("updated")})
			return err
		}, true},
		{"NewDiskCache", func(dc *DiskCache) error {
			_, err := NewDiskCache(dc.Path, dc.MaxSize)
			return err
		}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dc, err := NewDiskCache(t.TempDir(), 64)
			if err != nil {
				t.Fatal(err)
			}
			if _, err = dc.Add("key", map[string][]byte{"data": []byte("cached")}); err != nil {
				t.Fatal(err)
			}
			lock_path := filepath.Join(dc.Path, "lockfile")
			if err = os.Remove(lock_path); err != nil {
				t.Fatal(err)
			}
			if err = os.Mkdir(lock_path, 0o700); err != nil {
				t.Fatal(err)
			}
			if err = tc.run(dc); err == nil {
				t.Error("cache operation ignored failure to acquire the lock")
			}
			if tc.uses_dc {
				if !dc.lock_mutex.TryLock() {
					t.Fatal("failed lock attempt did not release the mutex")
				}
				dc.lock_mutex.Unlock()
				if dc.lock_file != nil {
					t.Fatal("failed lock attempt did not close the lock file")
				}
			}
			if err = os.Remove(lock_path); err != nil {
				t.Fatal(err)
			}
			paths, err := dc.Get("key", "data")
			if err != nil {
				t.Fatal(err)
			}
			data, err := os.ReadFile(paths["data"])
			if err != nil || string(data) != "cached" {
				t.Fatalf("cache data changed after a failed lock attempt: %q, %v", data, err)
			}
		})
	}
}
