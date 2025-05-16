// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type Match struct {
	Word        string `json:"word,omitempty"`
	Description string `json:"description,omitempty"`
}

type MatchGroup struct {
	Title           string   `json:"title,omitempty"`
	NoTrailingSpace bool     `json:"no_trailing_space,omitempty"`
	IsFiles         bool     `json:"is_files,omitempty"`
	Matches         []*Match `json:"matches,omitempty"`
}

func (self *MatchGroup) remove_common_prefix() string {
	if self.IsFiles {
		if len(self.Matches) > 1 {
			lcp := self.longest_common_prefix()
			if strings.Contains(lcp, utils.Sep) {
				lcp = strings.TrimRight(filepath.Dir(lcp), utils.Sep) + utils.Sep
				self.remove_prefix_from_all_matches(lcp)
				return lcp
			}
		}
	} else if len(self.Matches) > 1 && strings.HasPrefix(self.Matches[0].Word, "--") && strings.Contains(self.Matches[0].Word, "=") {
		lcp, _, _ := strings.Cut(self.longest_common_prefix(), "=")
		lcp += "="
		if len(lcp) > 3 {
			self.remove_prefix_from_all_matches(lcp)
			return lcp
		}
	}
	return ""
}

func (self *MatchGroup) AddMatch(word string, description ...string) *Match {
	ans := Match{Word: word, Description: strings.Join(description, " ")}
	self.Matches = append(self.Matches, &ans)
	return &ans
}

func (self *MatchGroup) AddPrefixToAllMatches(prefix string) {
	for _, m := range self.Matches {
		m.Word = prefix + m.Word
	}
}

func (self *MatchGroup) remove_prefix_from_all_matches(prefix string) {
	for _, m := range self.Matches {
		m.Word = m.Word[len(prefix):]
	}
}

func (self *MatchGroup) has_descriptions() bool {
	for _, m := range self.Matches {
		if m.Description != "" {
			return true
		}
	}
	return false
}

func (self *MatchGroup) max_visual_word_length(limit int) int {
	ans := 0
	for _, m := range self.Matches {
		if q := wcswidth.Stringwidth(m.Word); q > ans {
			ans = q
			if ans > limit {
				return limit
			}
		}
	}
	return ans
}

func (self *MatchGroup) longest_common_prefix() string {
	limit := len(self.Matches)
	i := 0
	return utils.LongestCommon(func() (string, bool) {
		if i < limit {
			i++
			return self.Matches[i-1].Word, false
		}
		return "", true
	}, true)
}

type Delegate struct {
	NumToRemove int    `json:"num_to_remove,omitempty"`
	Command     string `json:"command,omitempty"`
}

type Completions struct {
	Groups   []*MatchGroup `json:"groups,omitempty"`
	Delegate Delegate      `json:"delegate,omitempty"`

	CurrentCmd             *Command `json:"-"`
	AllWords               []string `json:"-"` // all words passed to parse_args()
	CurrentWordIdx         int      `json:"-"` // index of current word in all_words
	CurrentWordIdxInParent int      `json:"-"` // index of current word in parents command line 1 for first word after parent

	split_on_equals bool // true if the cmdline is split on = (BASH does this because readline does this)
}

func NewCompletions() *Completions {
	return &Completions{Groups: make([]*MatchGroup, 0, 4)}
}

func (self *Completions) AddPrefixToAllMatches(prefix string) {
	for _, mg := range self.Groups {
		mg.AddPrefixToAllMatches(prefix)
	}
}

func (self *Completions) MergeMatchGroup(mg *MatchGroup) {
	if len(mg.Matches) == 0 {
		return
	}
	var dest *MatchGroup
	for _, q := range self.Groups {
		if q.Title == mg.Title {
			dest = q
			break
		}
	}
	if dest == nil {
		dest = self.AddMatchGroup(mg.Title)
		dest.NoTrailingSpace = mg.NoTrailingSpace
		dest.IsFiles = mg.IsFiles
	}
	seen := utils.NewSet[string](64)
	for _, q := range self.Groups {
		for _, m := range q.Matches {
			seen.Add(m.Word)
		}
	}
	for _, m := range mg.Matches {
		if !seen.Has(m.Word) {
			seen.Add(m.Word)
			dest.Matches = append(dest.Matches, m)
		}
	}
}

func (self *Completions) AddMatchGroup(title string) *MatchGroup {
	for _, q := range self.Groups {
		if q.Title == title {
			return q
		}
	}
	ans := MatchGroup{Title: title, Matches: make([]*Match, 0, 8)}
	self.Groups = append(self.Groups, &ans)
	return &ans
}

type CompletionFunc = func(completions *Completions, word string, arg_num int)

func NamesCompleter(title string, names ...string) CompletionFunc {
	return func(completions *Completions, word string, arg_num int) {
		mg := completions.AddMatchGroup(title)
		for _, q := range names {
			if strings.HasPrefix(q, word) {
				mg.AddMatch(q)
			}
		}
	}
}

func ChainCompleters(completers ...CompletionFunc) CompletionFunc {
	return func(completions *Completions, word string, arg_num int) {
		for _, f := range completers {
			f(completions, word, arg_num)
		}
	}
}

func CompletionForWrapper(wrapped_cmd string) func(completions *Completions, word string, arg_num int) {
	return func(completions *Completions, word string, arg_num int) {
		completions.Delegate.NumToRemove = completions.CurrentWordIdx
		completions.Delegate.Command = wrapped_cmd
	}
}
