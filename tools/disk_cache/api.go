package disk_cache

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/kovidgoyal/kitty/tools/utils"
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
}

func NewDiskCache(path string, max_size int64) (dc *DiskCache, err error) {
	if path, err = filepath.Abs(path); err != nil {
		return
	}
	if err = os.MkdirAll(path, 0o700); err != nil {
		return
	}
	return &DiskCache{Path: path, MaxSize: max_size}, nil
}

func KeyForPath(path string) (key string, err error) {
	if path, err = filepath.EvalSymlinks(path); err != nil {
		return
	}
	if path, err = filepath.Abs(path); err != nil {
		return
	}

	s, err := os.Stat(path)
	if err != nil {
		return
	}
	data := fmt.Sprintf("%s\x00%d\x00%d", path, s.Size(), s.ModTime().UnixNano())
	sum := sha256.Sum256(utils.UnsafeStringToBytes(data))
	return hex.EncodeToString(sum[:]), nil
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
