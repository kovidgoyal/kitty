package disk_cache

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"time"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func new_disk_cache(path string, max_size int64) (dc *DiskCache, err error) {
	if path, err = filepath.Abs(path); err != nil {
		return
	}
	if err = os.MkdirAll(path, 0o700); err != nil {
		return
	}
	ans := &DiskCache{Path: path, MaxSize: max_size}
	ans.lock()
	defer ans.unlock()
	if err = ans.ensure_entries(); err != nil {
		return
	}
	if pruned, err := ans.prune(); err != nil {
		return nil, err
	} else if pruned {
		if err = ans.write_entries(); err != nil {
			return nil, err
		}
	}
	if ans.get_dir, err = os.MkdirTemp(ans.Path, "getdir-*"); err != nil {
		return
	}
	if err = utils.AtExitRmtree(ans.get_dir); err != nil {
		return
	}
	return ans, nil
}

func key_for_path(path string) (key string, err error) {
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

func (dc *DiskCache) lock() (err error) {
	dc.lock_mutex.Lock()
	defer dc.lock_mutex.Unlock()
	if dc.lock_file != nil {
		return
	}
	if dc.lock_file, err = os.OpenFile(filepath.Join(dc.Path, "lockfile"), os.O_RDWR|os.O_CREATE, 0o600); err != nil {
		return
	}
	return utils.LockFileExclusive(dc.lock_file)
}

func (dc *DiskCache) unlock() {
	dc.lock_mutex.Lock()
	defer dc.lock_mutex.Unlock()
	if dc.lock_file != nil {
		utils.UnlockFile(dc.lock_file)
		dc.lock_file.Close()
		dc.lock_file = nil
	}
}

func (dc *DiskCache) entries_path() string { return filepath.Join(dc.Path, "entries.json") }

func (dc *DiskCache) write_entries() (err error) {
	if d, err := json.Marshal(dc.entries); err != nil {
		return err
	} else {
		return os.WriteFile(dc.entries_path(), d, 0o600)
	}
}

func (dc *DiskCache) rebuild_entries() error {
	if entries, err := os.ReadDir(dc.Path); err != nil {
		return err
	} else {
		ans := make(map[string]*Entry)
		var total int64
		for _, x := range entries {
			if x.IsDir() {
				if sub_entries, err := os.ReadDir(filepath.Join(dc.Path, x.Name())); err == nil && len(sub_entries) == 1 {
					key := sub_entries[0].Name()
					path := dc.folder_for_key(key)
					if file_entries, err := os.ReadDir(path); err == nil {
						e := Entry{}
						for _, f := range file_entries {
							if fi, err := f.Info(); err == nil {
								e.Size += fi.Size()
								if fi.ModTime().After(e.LastUsed) {
									e.LastUsed = fi.ModTime()
								}
							}
						}
						ans[key] = &e
						total += e.Size
					}
				}
			}
		}
		sorted := utils.Values(ans)
		slices.SortFunc(sorted, func(a, b *Entry) int {
			return a.LastUsed.Compare(b.LastUsed)
		})
		dc.entries = Metadata{TotalSize: total, SortedEntries: sorted}
		dc.entry_map = ans
	}
	return nil
}

func (dc *DiskCache) ensure_entries() error {
	needed := dc.entry_map == nil
	path := dc.entries_path()
	if !needed {
		if s, err := os.Stat(path); err == nil && s.ModTime().After(dc.entries_mod_time) {
			needed = true
		}
	}
	if needed {
		if data, err := os.ReadFile(path); err != nil {
			if os.IsNotExist(err) {
				dc.entry_map = make(map[string]*Entry)
				dc.entries = Metadata{SortedEntries: make([]*Entry, 0)}
			} else {
				return err
			}
		} else {
			dc.entries = Metadata{SortedEntries: make([]*Entry, 0)}
			if err := json.Unmarshal(data, &dc.entries); err != nil {
				// corrupted data
				dc.rebuild_entries()
			}
			dc.entry_map = make(map[string]*Entry)
			for _, e := range dc.entries.SortedEntries {
				dc.entry_map[e.Key] = e
			}
		}
	}
	return nil
}

func (dc *DiskCache) folder_for_key(key string) (ans string) {
	if len(key) < 5 {
		ans = filepath.Join(key, key)
	} else {
		ans = filepath.Join(key[:4], key)
	}
	return filepath.Join(dc.Path, ans)
}

func (dc *DiskCache) update_last_used(key string) {
	if dc.ensure_entries() == nil {
		dc.update_timestamp(key)
	}

}

func (dc *DiskCache) get(key string, items []string) map[string]string {
	ans := make(map[string]string, len(items))
	base := dc.folder_for_key(key)
	if s, err := os.Stat(base); err != nil || !s.IsDir() {
		return ans
	}
	for _, x := range items {
		p := filepath.Join(base, x)
		if s, err := os.Stat(p); err != nil || s.IsDir() {
			continue
		}
		dest := filepath.Join(dc.get_dir, key+"-"+x)
		if err := os.Link(p, dest); err != nil {
			os.Remove(dest)
			if err := os.Link(p, dest); err != nil {
				dest = ""
			}
		}
		if dest != "" {
			ans[x] = dest
		}
	}
	dc.update_last_used(key)
	return ans
}

func (dc *DiskCache) remove(key string) (err error) {
	if err = dc.ensure_entries(); err != nil {
		return
	}
	base := dc.folder_for_key(key)
	if err = os.RemoveAll(base); err == nil {
		t := dc.entry_map[key]
		if t != nil {
			delete(dc.entry_map, key)
			dc.entries.TotalSize = max(0, dc.entries.TotalSize-t.Size)
			dc.entries.SortedEntries = utils.Filter(dc.entries.SortedEntries, func(x *Entry) bool { return x.Key != key })
			return dc.write_entries()
		}
	}
	return
}

func (dc *DiskCache) prune() (bool, error) {
	if dc.MaxSize < 1 || dc.entries.TotalSize <= dc.MaxSize {
		return false, nil
	}
	for dc.entries.TotalSize > dc.MaxSize && len(dc.entries.SortedEntries) > 0 {
		base := dc.folder_for_key(dc.entries.SortedEntries[0].Key)
		if err := os.RemoveAll(base); err == nil {
			t := dc.entries.SortedEntries[0]
			delete(dc.entry_map, t.Key)
			dc.entries.TotalSize = max(0, dc.entries.TotalSize-t.Size)
			dc.entries.SortedEntries = dc.entries.SortedEntries[1:]
		} else {
			return false, err
		}
	}
	return true, nil
}

func (dc *DiskCache) update_timestamp(key string) {
	t := dc.entry_map[key]
	t.LastUsed = time.Now()
	idx := slices.Index(dc.entries.SortedEntries, t)
	copy(dc.entries.SortedEntries[idx:], dc.entries.SortedEntries[idx+1:])
	dc.entries.SortedEntries[len(dc.entries.SortedEntries)-1] = t
}

func (dc *DiskCache) update_accounting(key string, changed int64) (err error) {
	t := dc.entry_map[key]
	if t == nil {
		t = &Entry{Key: key}
		dc.entry_map[key] = t
		dc.entries.SortedEntries = append(dc.entries.SortedEntries, t)
	}
	old_size := t.Size
	t.Size += changed
	t.Size = max(0, t.Size)
	dc.entries.TotalSize += t.Size - old_size
	dc.update_timestamp(key)
	dc.prune()
	return dc.write_entries()
}

func (dc *DiskCache) keys() (ans []string, err error) {
	if err = dc.ensure_entries(); err != nil {
		return
	}
	return utils.Keys(dc.entry_map), nil
}

func (dc *DiskCache) add(key string, items map[string][]byte) (err error) {
	if err = dc.ensure_entries(); err != nil {
		return
	}
	base := dc.folder_for_key(key)
	if err = os.MkdirAll(base, 0o700); err != nil {
		return err
	}
	var changed int64
	defer func() {
		e := dc.update_accounting(key, changed)
		if err == nil {
			err = e
		}
	}()
	for x, data := range items {
		p := filepath.Join(base, x)
		var before int64
		if s, err := os.Stat(p); err == nil {
			before = s.Size()
		}
		if len(data) == 0 {
			if err = os.Remove(p); err != nil {
				return
			}
			changed -= before
		} else {
			if err = os.WriteFile(p, data, 0o700); err != nil {
				return
			}
			changed += int64(len(data)) - before
		}
	}
	return
}
