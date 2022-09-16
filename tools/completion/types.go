// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import "strings"

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

func (self *MatchGroup) add_match(word string, description ...string) *Match {
	ans := Match{Word: word, Description: strings.Join(description, " ")}
	self.Matches = append(self.Matches, &ans)
	return &ans
}

type Completions struct {
	Groups []*MatchGroup `json:"groups,omitempty"`

	current_cmd      *Command
	all_words        []string // all words passed to parse_args()
	current_word_idx int      // index of current word in all_words
}

func (self *Completions) add_prefix_to_all_matches(prefix string) {
	for _, mg := range self.Groups {
		for _, m := range mg.Matches {
			m.Word = prefix + m.Word
		}
	}
}

func (self *Completions) add_match_group(title string) *MatchGroup {
	for _, q := range self.Groups {
		if q.Title == title {
			return q
		}
	}
	ans := MatchGroup{Title: title, Matches: make([]*Match, 0, 8)}
	self.Groups = append(self.Groups, &ans)
	return &ans
}

type completion_func func(completions *Completions, word string, arg_num int)

type Option struct {
	Name               string
	Aliases            []string
	Description        string
	Has_following_arg  bool
	Completion_for_arg completion_func
}

type CommandGroup struct {
	Title    string
	Commands []*Command
}

type Command struct {
	Name        string
	Description string

	Options []*Option
	Groups  []*CommandGroup

	Completion_for_arg              completion_func
	Stop_processing_at_arg          int
	First_arg_may_not_be_subcommand bool
	Subcommand_must_be_first        bool
}

func (self *Command) add_group(name string) *CommandGroup {
	for _, g := range self.Groups {
		if g.Title == name {
			return g
		}
	}
	g := CommandGroup{Title: name, Commands: make([]*Command, 0, 8)}
	self.Groups = append(self.Groups, &g)
	return &g
}

func (self *Command) add_command(name string, group_title string) *Command {
	ans := Command{Name: name}
	ans.Options = make([]*Option, 0, 8)
	ans.Groups = make([]*CommandGroup, 0, 2)
	g := self.add_group(group_title)
	g.Commands = append(g.Commands, &ans)
	return &ans
}

func (self *Command) add_clone(name string, group_title string, clone_of *Command) *Command {
	ans := *clone_of
	ans.Name = name
	g := self.add_group(group_title)
	g.Commands = append(g.Commands, &ans)
	return &ans
}

func (self *Command) find_subcommand(is_ok func(cmd *Command) bool) *Command {
	for _, g := range self.Groups {
		for _, q := range g.Commands {
			if is_ok(q) {
				return q
			}
		}
	}
	return nil
}

func (self *Command) find_subcommand_with_name(name string) *Command {
	return self.find_subcommand(func(cmd *Command) bool { return cmd.Name == name })
}

func (self *Command) has_subcommands() bool {
	for _, g := range self.Groups {
		if len(g.Commands) > 0 {
			return true
		}
	}
	return false
}

func (self *Command) sub_command_allowed_at(completions *Completions, arg_num int) bool {
	if self.Subcommand_must_be_first {
		return arg_num == 1 && completions.current_word_idx == 0
	}
	return arg_num == 1
}

func (self *Command) add_option(opt *Option) {
	self.Options = append(self.Options, opt)
}

func (self *Command) GetCompletions(argv []string) *Completions {
	ans := Completions{Groups: make([]*MatchGroup, 0, 4)}
	if len(argv) > 0 {
		exe := argv[0]
		cmd := self.find_subcommand_with_name(exe)
		if cmd != nil {
			cmd.parse_args(argv[1:], &ans)
		}
	}
	non_empty_groups := make([]*MatchGroup, 0, len(ans.Groups))
	for _, gr := range ans.Groups {
		if len(gr.Matches) > 0 {
			non_empty_groups = append(non_empty_groups, gr)
		}
	}
	ans.Groups = non_empty_groups
	return &ans
}

func names_completer(title string, names ...string) completion_func {
	return func(completions *Completions, word string, arg_num int) {
		mg := completions.add_match_group(title)
		for _, q := range names {
			if strings.HasPrefix(q, word) {
				mg.add_match(q)
			}
		}
	}
}

func chain_completers(completers ...completion_func) completion_func {
	return func(completions *Completions, word string, arg_num int) {
		for _, f := range completers {
			f(completions, word, arg_num)
		}
	}
}
