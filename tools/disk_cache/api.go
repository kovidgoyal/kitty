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
	SortedEntries []*Entry
}

type DiskCache struct {
	Path    string
	MaxSize int64

	lock_file        *os.File
	lock_mutex       sync.Mutex
	entries          Metadata
	entry_map        map[string]*Entry
	entries_mod_time time.Time
	get_dir          string
}

func NewDiskCache(path string, max_size int64) (dc *DiskCache, err error) {
	return new_disk_cache(path, max_size)
}

func KeyForPath(path string) (key string, err error) {
	return key_for_path(path)
}

func (dc *DiskCache) Get(key string, items ...string) map[string]string {
	dc.lock()
	defer dc.unlock()
	return dc.get(key, items)
}

func (dc *DiskCache) Remove(key string) (err error) {
	dc.lock()
	defer dc.unlock()
	return dc.remove(key)
}

func (dc *DiskCache) Add(key string, items map[string][]byte) (err error) {
	dc.lock()
	defer dc.unlock()
	return dc.add(key, items)
}
