// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package readline

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
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
	items                []HistoryItem
	prefix               string
	current_idx          int
	original_input_state InputState
}

type HistorySearch struct {
	query                string
	tokens               []string
	items                []*HistoryItem
	current_idx          int
	backwards            bool
	original_input_state InputState
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
	self.items = utils.StableSort(self.items, func(a, b HistoryItem) int {
		return a.Timestamp.Compare(b.Timestamp)
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

func (self *History) find_prefix_matches(prefix, current_command string, input_state InputState) *HistoryMatches {
	ans := HistoryMatches{items: make([]HistoryItem, 0, len(self.items)+1), prefix: prefix, original_input_state: input_state}
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

func (self *Readline) create_history_matches() {
	if self.last_action_was_history_movement() && self.history_matches != nil {
		return
	}
	prefix := self.text_upto_cursor_pos()
	self.history_matches = self.history.find_prefix_matches(prefix, self.AllText(), self.input_state.copy())
}

func (self *Readline) last_action_was_history_movement() bool {
	switch self.last_action {
	case ActionHistoryLast, ActionHistoryFirst, ActionHistoryNext, ActionHistoryPrevious:
		return true
	default:
		return false
	}
}

func (self *HistoryMatches) apply(rl *Readline) bool {
	if self.current_idx >= len(self.items) || self.current_idx < 0 {
		return false
	}
	if self.current_idx == len(self.items)-1 {
		rl.input_state = self.original_input_state.copy()
	} else {
		item := self.items[self.current_idx]
		rl.input_state.lines = utils.Splitlines(item.Cmd)
		if len(rl.input_state.lines) == 0 {
			rl.input_state.lines = []string{""}
		}
		idx := len(rl.input_state.lines) - 1
		rl.input_state.cursor = Position{Y: idx, X: len(rl.input_state.lines[idx])}
	}
	return true
}

func (self *HistoryMatches) first(rl *Readline) bool {
	self.current_idx = 0
	return self.apply(rl)
}

func (self *HistoryMatches) last(rl *Readline) bool {
	self.current_idx = max(0, len(self.items)-1)
	return self.apply(rl)
}

func (self *HistoryMatches) previous(num uint, rl *Readline) bool {
	if self.current_idx > 0 {
		self.current_idx = max(0, self.current_idx-int(num))
		return self.apply(rl)
	}
	return false
}

func (self *HistoryMatches) next(num uint, rl *Readline) bool {
	if self.current_idx+1 < len(self.items) {
		self.current_idx = min(len(self.items)-1, self.current_idx+int(num))
		return self.apply(rl)
	}
	return false
}

func (self *Readline) create_history_search(backwards bool, num uint) {
	self.history_search = &HistorySearch{backwards: backwards, original_input_state: self.input_state.copy()}
	self.push_keyboard_map(history_search_shortcuts())
	self.markup_history_search()
}

func (self *Readline) end_history_search(accept bool) {
	if accept && self.history_search.current_idx < len(self.history_search.items) {
		self.input_state.lines = utils.Splitlines(self.history_search.items[self.history_search.current_idx].Cmd)
		self.input_state.cursor.Y = len(self.input_state.lines) - 1
		self.input_state.cursor.X = len(self.input_state.lines[self.input_state.cursor.Y])
	} else {
		self.input_state = self.history_search.original_input_state
	}
	self.input_state.cursor = *self.ensure_position_in_bounds(&self.input_state.cursor)
	self.pop_keyboard_map()
	self.history_search = nil
}

func (self *Readline) markup_history_search() {
	if len(self.history_search.items) == 0 {
		if len(self.history_search.tokens) == 0 {
			self.input_state.lines = []string{""}
		} else {
			self.input_state.lines = []string{"No matches for: " + self.history_search.query}
		}
		self.input_state.cursor = Position{X: wcswidth.Stringwidth(self.input_state.lines[0])}
		return
	}
	lines := utils.Splitlines(self.history_search.items[self.history_search.current_idx].Cmd)
	cursor := Position{Y: len(lines)}
	for _, tok := range self.history_search.tokens {
		for i, line := range lines {
			if idx := strings.Index(line, tok); idx > -1 {
				q := Position{Y: i, X: idx}
				if q.Less(cursor) {
					cursor = q
				}
				break
			}
		}
	}
	self.input_state.lines = lines
	self.input_state.cursor = *self.ensure_position_in_bounds(&cursor)
}

func (self *Readline) remove_text_from_history_search(num uint) uint {
	l := len(self.history_search.query)
	nl := max(0, l-int(num))
	self.history_search.query = self.history_search.query[:nl]
	num_removed := uint(l - nl)
	self.add_text_to_history_search("") // update the search results
	return num_removed
}

func (self *Readline) history_search_highlighter(text string, x, y int) string {
	if len(self.history_search.items) == 0 {
		return text
	}
	lines := utils.Splitlines(text)
	for _, tok := range self.history_search.tokens {
		for i, line := range lines {
			if idx := strings.Index(line, tok); idx > -1 {
				lines[i] = line[:idx] + self.fmt_ctx.Green(tok) + line[idx+len(tok):]
				break
			}
		}
	}
	return strings.Join(lines, "\n")
}

func (self *Readline) add_text_to_history_search(text string) {
	self.history_search.query += text
	tokens, err := shlex.Split(self.history_search.query)
	if err != nil {
		tokens = strings.Split(self.history_search.query, " ")
	}
	self.history_search.tokens = tokens
	var current_item *HistoryItem
	if len(self.history_search.items) > 0 {
		current_item = self.history_search.items[self.history_search.current_idx]
	}
	if len(self.history_search.tokens) == 0 {
		self.history_search.items = []*HistoryItem{}
	} else {
		items := make([]*HistoryItem, len(self.history.items))
		for i := range self.history.items {
			items[i] = &self.history.items[i]
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
	}
	idx := -1
	for i, item := range self.history_search.items {
		if item == current_item {
			idx = i
			break
		}
	}
	if idx == -1 {
		if self.history_search.backwards {
			idx = len(self.history_search.items) - 1
		} else {
			idx = 0
		}
	}
	self.history_search.current_idx = max(0, idx)
	self.markup_history_search()
}

func (self *Readline) next_history_search(backwards bool, num uint) bool {
	ni := self.history_search.current_idx
	self.history_search.backwards = backwards
	if len(self.history_search.items) == 0 {
		return false
	}
	if backwards {
		ni = max(0, ni-int(num))
	} else {
		ni = min(ni+int(num), len(self.history_search.items)-1)
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

func (self *Readline) history_completer(before_cursor, after_cursor string) (ans *cli.Completions) {
	ans = cli.NewCompletions()
	if before_cursor != "" {
		var words_before_cursor []string
		words_before_cursor, ans.CurrentWordIdx = shlex.SplitForCompletion(before_cursor)
		idx := len(words_before_cursor)
		if idx > 0 {
			idx--
		}
		seen := utils.NewSet[string](16)
		mg := ans.AddMatchGroup("History")
		for _, x := range self.history.items {
			if strings.HasPrefix(x.Cmd, before_cursor) {
				words, _ := shlex.SplitForCompletion(x.Cmd)
				if idx < len(words) {
					word := words[idx]
					desc := ""
					if !seen.Has(word) {
						if word != x.Cmd {
							desc = x.Cmd
						}
						mg.AddMatch(word, desc)
						seen.Add(word)
					}
				}
			}
		}
	}

	return
}
