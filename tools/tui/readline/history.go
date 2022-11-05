// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"kitty/tools/utils"
)

var _ = fmt.Print

type HistoryItem struct {
	Cmd       string        `json:"cmd"`
	Cwd       string        `json:"cwd,omitempty"`
	Timestamp time.Time     `json:"timestamp"`
	Duration  time.Duration `json:"duration,omitempty"`
	ExitCode  int           `json:"exit_code"`
}

type HistoryMatches struct {
	items       []HistoryItem
	prefix      string
	current_idx int
}

type History struct {
	file_path string
	file      *os.File
	max_items int
	items     []HistoryItem
	cmd_map   map[string]int
}

func map_from_items(items []HistoryItem) map[string]int {
	pmap := make(map[string]int, len(items))
	for i, hi := range items {
		pmap[hi.Cmd] = i
	}
	return pmap
}

func (self *History) add_item(x HistoryItem) bool {
	existing, found := self.cmd_map[x.Cmd]
	if found {
		if self.items[existing].Timestamp.Before(x.Timestamp) {
			self.items[existing] = x
			return true
		}
		return false
	}
	self.cmd_map[x.Cmd] = len(self.items)
	self.items = append(self.items, x)
	return true
}

func (self *History) merge_items(items ...HistoryItem) {
	if len(self.items) == 0 {
		self.items = items
		self.cmd_map = map_from_items(self.items)
		return
	}
	if len(items) == 0 {
		return
	}
	changed := false
	for _, x := range items {
		if self.add_item(x) {
			changed = true
		}
	}
	if !changed {
		return
	}
	self.items = utils.StableSort(self.items, func(a, b HistoryItem) bool {
		return a.Timestamp.Before(b.Timestamp)
	})
	if len(self.items) > self.max_items {
		self.items = self.items[len(self.items)-self.max_items:]
	}
	self.cmd_map = map_from_items(self.items)
}

func (self *History) Write() {
	if self.file == nil {
		return
	}
	self.file.Seek(0, 0)
	utils.LockFileExclusive(self.file)
	defer utils.UnlockFile(self.file)
	data, err := io.ReadAll(self.file)
	if err != nil {
		return
	}
	var items []HistoryItem
	err = json.Unmarshal(data, &items)
	if err != nil {
		self.merge_items(items...)
	}
	ndata, err := json.MarshalIndent(self.items, "", "  ")
	if err != nil {
		return
	}
	self.file.Truncate(int64(len(ndata)))
	self.file.Seek(0, 0)
	self.file.Write(ndata)
}

func (self *History) Read() {
	if self.file == nil {
		return
	}
	self.file.Seek(0, 0)
	utils.LockFileShared(self.file)
	data, err := io.ReadAll(self.file)
	utils.UnlockFile(self.file)
	if err != nil {
		return
	}
	var items []HistoryItem
	err = json.Unmarshal(data, &items)
	if err != nil {
		self.merge_items(items...)
	}
}

func (self *History) AddItem(cmd string, duration time.Duration) {
	self.merge_items(HistoryItem{Cmd: cmd, Duration: duration, Timestamp: time.Now()})
}

func (self *History) Shutdown() {
	if self.file != nil {
		self.Write()
		self.file.Close()
		self.file = nil
	}
}

func NewHistory(path string, max_items int) *History {
	ans := History{items: []HistoryItem{}, cmd_map: map[string]int{}, max_items: max_items}
	if path != "" {
		ans.file_path = path
		f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0o600)
		if err == nil {
			ans.file = f
		} else {
			fmt.Fprintln(os.Stderr, "Failed to open history file at:", path, "with error:", err)
		}
	}
	ans.Read()
	return &ans
}

func (self *History) FindPrefixMatches(prefix, current_command string) *HistoryMatches {
	ans := HistoryMatches{items: make([]HistoryItem, 0, len(self.items)+1), prefix: prefix}
	if prefix == "" {
		ans.items = ans.items[:len(self.items)]
		copy(ans.items, self.items)
	} else {
		for _, x := range self.items {
			if strings.HasPrefix(x.Cmd, prefix) {
				ans.items = append(ans.items, x)
			}
		}
	}
	ans.items = append(ans.items, HistoryItem{Cmd: current_command})
	ans.current_idx = len(ans.items) - 1
	return &ans
}

func (self *HistoryMatches) first() (ans *HistoryItem) {
	self.current_idx = 0
	return &self.items[self.current_idx]
}

func (self *HistoryMatches) last() (ans *HistoryItem) {
	self.current_idx = len(self.items) - 1
	return &self.items[self.current_idx]
}

func (self *HistoryMatches) previous(num uint) (ans *HistoryItem) {
	if self.current_idx > 0 {
		self.current_idx = utils.Max(0, self.current_idx-int(num))
		ans = &self.items[self.current_idx]
	}
	return
}

func (self *HistoryMatches) next(num uint) (ans *HistoryItem) {
	if self.current_idx+1 < len(self.items) {
		self.current_idx = utils.Min(len(self.items)-1, self.current_idx+int(num))
		ans = &self.items[self.current_idx]
	}
	return
}
