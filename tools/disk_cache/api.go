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

func (dc *DiskCache) Get(key string, items ...string) (map[string]string, error) {
	dc.lock()
	defer dc.unlock()
	return dc.get(key, items)
}

func (dc *DiskCache) GetPath(path string, items ...string) (string, map[string]string, error) {
	dc.lock()
	defer dc.unlock()
	key, err := key_for_path(path)
	if err != nil {
		return "", nil, err
	}
	ans, err := dc.get(key, items)
	return key, ans, err
}

func (dc *DiskCache) Remove(key string) (err error) {
	dc.lock()
	defer dc.unlock()
	return dc.remove(key)
}

func (dc *DiskCache) Clear() (err error) {
	dc.lock()
	defer dc.unlock()
	return dc.clear()
}

func (dc *DiskCache) AddPath(path, key string, items map[string][]byte) (ans map[string]string, err error) {
	dc.lock()
	defer dc.unlock()
	ans, err = dc.add_path(path, key, items)
	return
}

func (dc *DiskCache) Add(key string, items map[string][]byte) (ans map[string]string, err error) {
	dc.lock()
	defer dc.unlock()
	return dc.add(key, items)
}
