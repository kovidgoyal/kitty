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
	"kitty/tools/wcswidth"
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

type HistorySearch struct {
	query           string
	tokens          []string
	items           []*HistoryItem
	current_idx     int
	backwards       bool
	original_lines  []string
	original_cursor Position
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
	if err == nil {
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

func (self *Readline) create_history_search(backwards bool, num uint) {
	self.history_search = &HistorySearch{backwards: backwards, original_lines: self.lines, original_cursor: self.cursor}
	self.markup_history_search()
}

func (self *Readline) end_history_search(accept bool) {
	self.cursor = Position{}
	if accept && self.history_search.current_idx < len(self.history_search.items) {
		self.lines = utils.Splitlines(self.history_search.items[self.history_search.current_idx].Cmd)
		self.cursor.Y = len(self.lines) - 1
		self.cursor.X = len(self.lines[self.cursor.Y])
	} else {
		self.lines = self.history_search.original_lines
		self.cursor = self.history_search.original_cursor
	}
	self.cursor = *self.ensure_position_in_bounds(&self.cursor)
}

func (self *Readline) markup_history_search() {
	if len(self.history_search.items) == 0 {
		if len(self.history_search.tokens) == 0 {
			self.lines = []string{""}
		} else {
			self.lines = []string{"No matches for: " + self.fmt_ctx.BrightRed(self.history_search.query)}
		}
		self.cursor = Position{X: wcswidth.Stringwidth(self.lines[0])}
		return
	}
	lines := utils.Splitlines(self.history_search.items[self.history_search.current_idx].Cmd)
	cursor := Position{Y: len(lines)}
	for _, tok := range self.history_search.tokens {
		for i, line := range lines {
			if idx := strings.Index(line, tok); idx > -1 {
				lines[i] = line[:idx] + self.fmt_ctx.Green(tok) + line[idx+len(tok):]
				q := Position{Y: i, X: idx}
				if q.Less(cursor) {
					cursor = q
				}
				break
			}
		}
	}
	self.lines = lines
	self.cursor = *self.ensure_position_in_bounds(&cursor)
}

func (self *Readline) add_text_to_history_search(text string) {
	self.history_search.query += text
	self.history_search.tokens = strings.Split(self.history_search.query, " ")
	var current_item *HistoryItem
	if len(self.history_search.items) > 0 {
		current_item = self.history_search.items[self.history_search.current_idx]
	}
	items := make([]*HistoryItem, len(self.history.items))
	for i, x := range self.history.items {
		items[i] = &x
	}
	for _, token := range self.history_search.tokens {
		matches := make([]*HistoryItem, 0, len(items))
		for _, item := range items {
			if strings.Contains(item.Cmd, token) {
				matches = append(matches, item)
			}
		}
		items = matches
	}
	self.history_search.items = items
	idx := -1
	for i, item := range self.history_search.items {
		if item == current_item {
			idx = i
			break
		}
	}
	if idx == -1 {
		idx = len(self.history_search.items) - 1
	}
	self.history_search.current_idx = utils.Max(0, idx)
	self.markup_history_search()
}

func (self *Readline) next_history_search(backwards bool, num uint) bool {
	ni := self.history_search.current_idx
	self.history_search.backwards = backwards
	if len(self.history_search.items) == 0 {
		return false
	}
	if backwards {
		ni = utils.Max(0, ni-int(num))
	} else {
		ni = utils.Min(ni+int(num), len(self.history_search.items)-1)
	}
	if ni == self.history_search.current_idx {
		return false
	}
	self.history_search.current_idx = ni
	self.markup_history_search()
	return true
}

func (self *Readline) history_search_prompt() string {
	ans := "↑"
	if !self.history_search.backwards {
		ans = "↓"
	}
	failed := len(self.history_search.tokens) > 0 && len(self.history_search.items) == 0
	if failed {
		ans = self.fmt_ctx.BrightRed(ans)
	} else {
		ans = self.fmt_ctx.Green(ans)
	}
	return fmt.Sprintf("history %s: ", ans)
}
