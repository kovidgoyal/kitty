package disk_cache

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/fs"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"time"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type file_state struct {
	Size    int64
	ModTime time.Time
	Inode   uint64
}

func (s file_state) String() string {
	return fmt.Sprintf("fs{Size: %d, Inode: %d, ModTime: %s}", s.Size, s.Inode, s.ModTime)
}

func (s *file_state) equal(o *file_state) bool {
	return o != nil && s.Size == o.Size && s.ModTime.Equal(o.ModTime) && s.Inode == o.Inode
}

func get_file_state(fi fs.FileInfo) *file_state {
	// The Sys() method returns the underlying data source (can be nil).
	// For Unix-like systems, it's a *syscall.Stat_t.
	stat, ok := fi.Sys().(*syscall.Stat_t)
	if !ok {
		// For non-Unix systems, you might not have an inode.
		// In that case, you can fall back to using only size and mod time.
		return &file_state{
			Size:    fi.Size(),
			ModTime: fi.ModTime(),
			Inode:   0, // Inode not available
		}
	}
	return &file_state{
		Size:    fi.Size(),
		ModTime: fi.ModTime(),
		Inode:   stat.Ino,
	}
}

func get_file_state_from_path(path string) (*file_state, error) {
	if s, err := os.Stat(path); err != nil {
		return nil, err
	} else {
		return get_file_state(s), nil
	}
}

const GET_DIR_PREFIX = "getdir-"

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
	defer func() {
		if we := ans.write_entries_if_dirty(); we != nil && err == nil {
			err = we
		}
	}()
	if _, err := ans.prune(); err != nil {
		return nil, err
	}
	if ans.get_dir, err = os.MkdirTemp(ans.Path, GET_DIR_PREFIX+"*"); err != nil {
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

const ENTRIES_NAME = "entries.json"

func (dc *DiskCache) entries_path() string { return filepath.Join(dc.Path, ENTRIES_NAME) }

func (dc *DiskCache) write_entries_if_dirty() (err error) {
	if !dc.entries_dirty {
		return
	}
	path := dc.entries_path()
	defer func() {
		if err == nil {
			dc.entries_dirty = false
			if s, serr := get_file_state_from_path(path); serr == nil {
				dc.entries_last_read_state = s
			}
		}
	}()
	if d, err := json.Marshal(dc.entries); err != nil {
		return err
	} else {
		// use a rename so that the inode number changes
		// dont bother with full utils.AtomicWriteFile() as it is slower
		temp := path + ".temp"
		removed := false
		defer func() {
			if !removed {
				_ = os.Remove(temp)
				removed = true
			}
		}()
		if err = os.WriteFile(temp, d, 0o600); err == nil {
			if err = os.Rename(temp, path); err == nil {
				removed = true
			}
		}
		return err
	}
}

func (e Entry) String() string {
	return fmt.Sprintf("Entry{Key: %s, Size: %d, LastUsed: %s}", e.Key, e.Size, e.LastUsed)
}

func (dc *DiskCache) entries_from_folders() (total_size int64, ans map[string]*Entry, sorted []*Entry, err error) {
	if entries, err := os.ReadDir(dc.Path); err != nil {
		return 0, nil, nil, err
	} else {
		ans = make(map[string]*Entry)
		var total int64
		for _, x := range entries {
			if x.IsDir() {
				if sub_entries, err := os.ReadDir(filepath.Join(dc.Path, x.Name())); err == nil && len(sub_entries) == 1 {
					key := sub_entries[0].Name()
					path := dc.folder_for_key(key)
					if file_entries, err := os.ReadDir(path); err == nil {
						e := Entry{Key: key}
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
		sorted = utils.Values(ans)
		slices.SortFunc(sorted, func(a, b *Entry) int {
			return a.LastUsed.Compare(b.LastUsed)
		})
		return total, ans, sorted, nil
	}
}

func (dc *DiskCache) rebuild_entries() error {
	total, ans, sorted, err := dc.entries_from_folders()
	if err != nil {
		return err
	}
	dc.entries = Metadata{TotalSize: total, SortedEntries: sorted, PathMap: make(map[string]string)}
	dc.entry_map = ans
	dc.entries_dirty = true
	return dc.write_entries_if_dirty()
}

func (dc *DiskCache) ensure_entries() error {
	needed := dc.entry_map == nil || dc.entries_last_read_state == nil
	path := dc.entries_path()
	var fstate *file_state
	if !needed {
		if s, err := get_file_state_from_path(path); err == nil {
			fstate = s
			if !s.equal(dc.entries_last_read_state) {
				needed = true
			}
		}
	}
	if needed {
		if data, err := os.ReadFile(path); err != nil {
			if os.IsNotExist(err) {
				dc.entry_map = make(map[string]*Entry)
				dc.entries = Metadata{SortedEntries: make([]*Entry, 0), PathMap: make(map[string]string)}
			} else {
				return err
			}
		} else {
			dc.read_count += 1
			dc.entries = Metadata{SortedEntries: make([]*Entry, 0), PathMap: make(map[string]string)}
			if err := json.Unmarshal(data, &dc.entries); err != nil {
				// corrupted data
				dc.rebuild_entries()
			} else {
				if fstate == nil {
					if s, err := get_file_state_from_path(path); err == nil {
						fstate = s
					}
				}
				dc.entries_last_read_state = fstate
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

func (dc *DiskCache) export_to_get_dir(key, path string) (string, error) {
	dest := filepath.Join(dc.get_dir, key+"-"+filepath.Base(path))
	if err := os.Link(path, dest); err != nil {
		os.Remove(dest)
		if err := os.Link(path, dest); err != nil {
			return "", err
		}
	}
	return dest, nil

}

func (dc *DiskCache) get(key string, items []string) (map[string]string, error) {
	if err := dc.ensure_entries(); err != nil {
		return nil, err
	}
	base := dc.folder_for_key(key)
	if len(items) == 0 {
		if entries, err := os.ReadDir(base); err != nil {
			if os.IsNotExist(err) {
				err = nil
			}
			return nil, err
		} else {
			for _, e := range entries {
				items = append(items, e.Name())
			}
		}
	} else {
		if s, err := os.Stat(base); err != nil || !s.IsDir() {
			if os.IsNotExist(err) {
				err = nil
			}
			return nil, err
		}
	}
	ans := make(map[string]string, len(items))
	for _, x := range items {
		p := filepath.Join(base, x)
		if s, err := os.Stat(p); err != nil || s.IsDir() {
			continue
		}
		dest, _ := dc.export_to_get_dir(key, p)
		if dest != "" {
			ans[x] = dest
		}
	}
	if len(items) > 0 {
		dc.update_timestamp(key)
	}
	return ans, dc.write_entries_if_dirty()
}

func (dc *DiskCache) clear() (err error) {
	if entries, err := os.ReadDir(dc.Path); err != nil {
		return err
	} else {
		defer func() {
			if we := dc.write_entries_if_dirty(); we != nil && err == nil {
				err = we
			}
		}()
		for _, x := range entries {
			if x.IsDir() && !strings.HasPrefix(x.Name(), GET_DIR_PREFIX) {
				_ = os.RemoveAll(filepath.Join(dc.Path, x.Name()))
			}
		}
		dc.entries_dirty = true
		dc.entry_map = make(map[string]*Entry)
		dc.entries.SortedEntries = make([]*Entry, 0)
		dc.entries.TotalSize = 0
	}
	return
}

func (dc *DiskCache) remove(key string) (err error) {
	if err = dc.ensure_entries(); err != nil {
		return
	}
	defer func() {
		if we := dc.write_entries_if_dirty(); we != nil && err == nil {
			err = we
		}
	}()
	base := dc.folder_for_key(key)
	if err = os.RemoveAll(base); err == nil {
		t := dc.entry_map[key]
		if t != nil {
			delete(dc.entry_map, key)
			dc.entries.TotalSize = max(0, dc.entries.TotalSize-t.Size)
			dc.entries.SortedEntries = utils.Filter(dc.entries.SortedEntries, func(x *Entry) bool { return x.Key != key })
			dc.entries_dirty = true
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
			maps.DeleteFunc(dc.entries.PathMap, func(path, key string) bool { return key == t.Key })
			dc.entries.TotalSize = max(0, dc.entries.TotalSize-t.Size)
			dc.entries.SortedEntries = dc.entries.SortedEntries[1:]
			dc.entries_dirty = true
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
	dc.entries_dirty = true
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
	dc.entries_dirty = true
	dc.update_timestamp(key)
	dc.prune()
	return dc.write_entries_if_dirty()
}

func (dc *DiskCache) keys() (ans []string, err error) {
	if err = dc.ensure_entries(); err != nil {
		return
	}
	ans = make([]string, len(dc.entries.SortedEntries))
	for i, e := range dc.entries.SortedEntries {
		ans[i] = e.Key
	}
	return
}

func (dc *DiskCache) add_path(path, key string, items map[string][]byte) (ans map[string]string, err error) {
	if err = dc.ensure_entries(); err != nil {
		return
	}
	defer func() {
		if we := dc.write_entries_if_dirty(); we != nil && err == nil {
			err = we
		}
	}()

	if existing := dc.entries.PathMap[path]; existing != "" && existing != key {
		delete(dc.entries.PathMap, path)
		dc.entries_dirty = true
		if err = dc.remove(existing); err != nil {
			return
		}
	}
	dc.entries.PathMap[path] = key
	dc.entries_dirty = true
	return dc.add(key, items)
}

func (dc *DiskCache) add(key string, items map[string][]byte) (ans map[string]string, err error) {
	if err = dc.ensure_entries(); err != nil {
		return
	}
	base := dc.folder_for_key(key)
	if err = os.MkdirAll(base, 0o700); err != nil {
		return
	}
	var changed int64
	defer func() {
		e := dc.update_accounting(key, changed)
		if err == nil {
			err = e
		}
	}()
	ans = make(map[string]string, len(items))
	for x, data := range items {
		p := filepath.Join(base, x)
		var before int64
		exists := false
		if s, err := os.Stat(p); err == nil {
			before = s.Size()
			exists = true
		}
		if len(data) == 0 {
			if exists {
				if err = os.Remove(p); err != nil {
					if !os.IsNotExist(err) {
						return
					}
					err = nil
				}
				changed -= before
			}
		} else {
			// unlink the file so that writing to it does not change a
			// previously linked copy created by get()
			if exists {
				_ = os.Remove(p)
			}
			if err = os.WriteFile(p, data, 0o700); err != nil {
				return
			}
			changed += int64(len(data)) - before
			if dest, err := dc.export_to_get_dir(key, p); err != nil {
				return ans, err
			} else {
				ans[x] = dest
			}
		}
	}
	return
}
