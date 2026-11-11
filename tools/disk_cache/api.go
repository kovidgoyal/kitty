package disk_cache

import (
	"fmt"
	"os"
	"sync"
	"time"
)

var _ = fmt.Print

type Entry struct {
	Key      string
	Size     int64
	LastUsed time.Time
}

type Metadata struct {
	TotalSize     int64
	PathMap       map[string]string
	SortedEntries []*Entry
}

type DiskCache struct {
	Path    string
	MaxSize int64

	lock_file               *os.File
	lock_mutex              sync.Mutex
	entries                 Metadata
	entry_map               map[string]*Entry
	entries_last_read_state *file_state
	entries_dirty           bool
	get_dir                 string
	read_count              int
}

func NewDiskCache(path string, max_size int64) (dc *DiskCache, err error) {
	return new_disk_cache(path, max_size)
}

func (dc *DiskCache) ResultsDir() string {
	return dc.get_dir
}

func (dc *DiskCache) unlock_and_set_err(err *error) {
	if ue := dc.unlock(); ue != nil && *err == nil {
		*err = ue
	}
}

func (dc *DiskCache) Get(key string, items ...string) (ans map[string]string, err error) {
	if err = dc.lock(); err != nil {
		return
	}
	defer dc.unlock_and_set_err(&err)
	return dc.get(key, items)
}

// GetPath returns the cache key for the file at path and the cached items for
// that key. The key depends on the resolved path of the file, its size and its
// modification time. Use extra_key to add anything else the cached data
// depends on, such as the command used to generate it. extra_key is used
// verbatim, it is not normalized in any way. Pass the same path and extra_key
// to AddPath() when adding the items for key.
func (dc *DiskCache) GetPath(path, extra_key string, items ...string) (key string, ans map[string]string, err error) {
	if err = dc.lock(); err != nil {
		return
	}
	defer dc.unlock_and_set_err(&err)
	if key, err = key_for_path(path, extra_key); err != nil {
		return "", nil, err
	}
	if ans, err = dc.get(key, items); err == nil && len(ans) > 0 {
		// Record which entry path now uses so that its previous entry is
		// removed once no other path uses it.
		if orphan := dc.set_key_for_path(path_map_key(path, extra_key), key); orphan != "" {
			// Removing the orphan is only cleanup, failing to do so must not
			// discard the valid result. The orphan is still tracked, so
			// pruning removes it eventually.
			_ = dc.remove(orphan)
		}
		err = dc.write_entries_if_dirty()
	}
	return
}

func (dc *DiskCache) Remove(key string) (err error) {
	if err = dc.lock(); err != nil {
		return
	}
	defer dc.unlock_and_set_err(&err)
	return dc.remove(key)
}

func (dc *DiskCache) Clear() (err error) {
	if err = dc.lock(); err != nil {
		return
	}
	defer dc.unlock_and_set_err(&err)
	return dc.clear()
}

// AddPath adds items for the key returned by GetPath(path, extra_key).
func (dc *DiskCache) AddPath(path, extra_key, key string, items map[string][]byte) (ans map[string]string, err error) {
	if err = dc.lock(); err != nil {
		return
	}
	defer dc.unlock_and_set_err(&err)
	return dc.add_path(path_map_key(path, extra_key), key, items)
}

func (dc *DiskCache) Add(key string, items map[string][]byte) (ans map[string]string, err error) {
	if err = dc.lock(); err != nil {
		return
	}
	defer dc.unlock_and_set_err(&err)
	return dc.add(key, items)
}
